#!/usr/bin/env python3
"""Create redacted, archive-bound Stage 3 v3 supply-chain evidence."""
from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SHA=re.compile(r"^[0-9a-f]{64}$")
GIT_SHA=re.compile(r"^[0-9a-f]{40}$")
BAD=re.compile(r"https?://|[a-z]:[\\/]|authorization|credential|password|secret|token|api[_-]?key|database[_-]?url|dsn",re.I)
class EvidenceError(RuntimeError): pass
def checksum(path:Path)->str:
 d=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): d.update(b)
 return d.hexdigest()
def now()->str:return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def load(path:Path)->dict[str,Any]:
 try:v=json.loads(path.read_text(encoding="utf-8-sig"))
 except (OSError,json.JSONDecodeError) as e:raise EvidenceError(f"invalid_json:{path.name}") from e
 if not isinstance(v,dict):raise EvidenceError(f"invalid_json_object:{path.name}")
 return v
def safe(value:Any)->str:
 value=str(value or "")
 return "[redacted]" if BAD.search(value) else value
def write(path:Path,value:Any)->None:
 encoded=json.dumps(value,ensure_ascii=True,sort_keys=True)
 if BAD.search(encoded):raise EvidenceError("evidence_redaction_rejected")
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=True,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def tool(data:list[dict[str,Any]],name:str)->dict[str,str]:
 item=next((x for x in data if x.get("name")==name),None)
 if not isinstance(item,dict) or item.get("platform")!="windows/amd64" or item.get("checksum_verified") is not True:raise EvidenceError(f"tool_verification_failed:{name}")
 asset,sums=str(item.get("asset_sha256","")),str(item.get("checksums_sha256",""))
 if not SHA.fullmatch(asset) or not SHA.fullmatch(sums) or not item.get("version"):raise EvidenceError(f"tool_verification_invalid:{name}")
 return {"name":name,"version":str(item["version"]),"platform":"windows/amd64","source_verification":"official_release_checksum_verified","asset_sha256":asset,"checksums_sha256":sums}
def database(raw:dict[str,Any])->dict[str,Any]:
 source=str(raw.get("from",""));ck=re.search(r"checksum=sha256%3A([0-9a-f]{64})",source);ts=re.search(r"_(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ)_",source)
 if not source.startswith("https://grype.anchore.io/databases/") or not ck or not ts or not raw.get("schemaVersion") or raw.get("valid") is not True:raise EvidenceError("database_verification_failed")
 return {"status":"current","schema_version":str(raw["schemaVersion"]),"updated_at":ts.group(1),"built_at":str(raw.get("built","")),"checksum":ck.group(1),"source_verification":"official_anchore_database_checksum_verified","valid":True}
def spdx(raw:dict[str,Any],name:str,digest:str,created:str,scanner:dict[str,str])->dict[str,Any]:
 packages=[]
 for n,p in enumerate(raw.get("packages",[]),1):
  if not isinstance(p,dict):continue
  refs=[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":safe(x.get("referenceLocator"))} for x in p.get("externalRefs",[]) if isinstance(x,dict) and x.get("referenceType")=="purl" and safe(x.get("referenceLocator"))!="[redacted]"]
  packages.append({"SPDXID":f"SPDXRef-Package-{n}","name":safe(p.get("name")),"versionInfo":safe(p.get("versionInfo")),"downloadLocation":"NOASSERTION","filesAnalyzed":False,"licenseConcluded":safe(p.get("licenseConcluded") or "NOASSERTION"),"licenseDeclared":safe(p.get("licenseDeclared") or "NOASSERTION"),"externalRefs":refs})
 if not packages:raise EvidenceError(f"sbom_empty:{name}")
 return {"spdxVersion":str(raw.get("spdxVersion","SPDX-2.3")),"dataLicense":"CC0-1.0","SPDXID":"SPDXRef-DOCUMENT","name":f"raganything-{name}-sbom","documentNamespace":f"urn:stage3:{digest}","creationInfo":{"created":created,"creators":[f"Tool: Syft-{scanner['version']}"]},"packages":packages,"relationships":[{"spdxElementId":"SPDXRef-DOCUMENT","relationshipType":"DESCRIBES","relatedSpdxElement":p["SPDXID"]} for p in packages]}

def licenses(doc:dict[str,Any])->dict[str,Any]:
 packages=[{"name":p["name"],"version":p["versionInfo"],"license_concluded":p["licenseConcluded"],"license_declared":p["licenseDeclared"]} for p in doc["packages"]]
 counts:dict[str,int]={}
 for p in packages:counts[p["license_declared"]]=counts.get(p["license_declared"],0)+1
 return {"package_count":len(packages),"declared_license_counts":dict(sorted(counts.items())),"packages":packages}
def vulnerabilities(raw:dict[str,Any])->dict[str,Any]:
 matches=[]
 for m in raw.get("matches",[]):
  if not isinstance(m,dict):continue
  a,v=m.get("artifact",{}),m.get("vulnerability",{})
  if not isinstance(a,dict) or not isinstance(v,dict):continue
  fix=v.get("fix") if isinstance(v.get("fix"),dict) else {}
  matches.append({"artifact":{"name":safe(a.get("name")),"version":safe(a.get("version")),"type":safe(a.get("type")),"language":safe(a.get("language")),"purl":safe(a.get("purl")),"licenses":[safe(x) for x in a.get("licenses",[]) if safe(x)!="[redacted]"]},"vulnerability":{"id":safe(v.get("id")),"namespace":safe(v.get("namespace")),"severity":safe(v.get("severity")),"fix":{"state":safe(fix.get("state")),"versions":[safe(x) for x in fix.get("versions",[]) if safe(x)!="[redacted]"]}}})
 return {"match_count":len(matches),"matches":matches}
def sums(bundle:Path)->str:
 target=bundle/"SHA256SUMS";records=[]
 for item in sorted((x for x in bundle.rglob("*") if x.is_file() and x!=target),key=lambda x:x.relative_to(bundle).as_posix()):
  if item.is_symlink():raise EvidenceError("bundle_symlink_rejected")
  records.append(f"{checksum(item)}  {item.relative_to(bundle).as_posix()}")
 target.write_text("\n".join(records)+"\n",encoding="utf-8");return checksum(target)
def qualify(*,bundle:Path,raw_dir:Path,tool_verification:Path,database_status:Path)->dict[str,Any]:
 identity_path=bundle/"manifests"/"oci-identity.json";identity=load(identity_path);tools=json.loads(tool_verification.read_text(encoding="utf-8"));db=database(load(database_status))
 if not isinstance(tools,list):raise EvidenceError("tool_verification_invalid")
 syft,grype=tool(tools,"syft"),tool(tools,"grype");archives=identity.get("archive_provenance",{}).get("archives")
 if not isinstance(archives,dict) or set(archives)!={"candidate","rollback","postgres","redis","nginx"}:raise EvidenceError("archive_provenance_invalid")
 created,manifest=now(),{}
 for name in ("candidate","rollback"):
  image=identity.get(name)
  if not isinstance(image,dict) or image.get("platform")!="linux/amd64" or not str(image.get("digest","")).startswith("sha256:") or not GIT_SHA.fullmatch(str(image.get("revision",""))):raise EvidenceError(f"image_identity_invalid:{name}")
  if checksum(bundle/"images"/f"{name}.tar")!=archives[name]:raise EvidenceError(f"archive_mismatch:{name}")
  raw_spdx,raw_grype=load(raw_dir/f"{name}-raw.spdx.json"),load(raw_dir/f"{name}-raw.grype.json");doc=spdx(raw_spdx,name,image["digest"],created,syft)
  common={"schema_version":1,"completion_status":"complete","status":"passed","generated_at":created,"archive_sha256":archives[name],"image_digest":image["digest"],"image_revision":image["revision"],"platform":"linux/amd64","database":db}
  records={"sbom":{**common,"artifact":"sbom","output_format":"spdx-json","scanner":syft,"raw_output_sha256":checksum(raw_dir/f"{name}-raw.spdx.json"),"sbom":doc},"licenses":{**common,"artifact":"license-inventory","output_format":"json","scanner":syft,"raw_output_sha256":checksum(raw_dir/f"{name}-raw.spdx.json"),"license_inventory":licenses(doc)},"vulnerabilities":{**common,"artifact":"vulnerability-snapshot","output_format":"grype-json","scanner":grype,"raw_output_sha256":checksum(raw_dir/f"{name}-raw.grype.json"),"vulnerabilities":vulnerabilities(raw_grype)}}
  manifest[name]={}
  for kind,record in records.items():
   relative=f"evidence/supply-chain/{name}-{kind}.json";target=bundle/relative;write(target,record);manifest[name][kind]={"path":relative,"sha256":checksum(target)}
 supply={"archive_checksums":archives,"artifacts":manifest,"created_at":created,"qualification":"offline-release-qualified","v2_root_sha256":identity.get("v3_supply_chain",{}).get("source_v2_sha256sums"),"v3_archive_copy":"byte-identical","vulnerability_database":db}
 write(bundle/"manifests"/"supply-chain.json",supply);identity["v3_supply_chain"]={"qualification":"offline-release-qualified","source_v2_sha256sums":supply["v2_root_sha256"],"archives":archives};write(identity_path,identity)
 root=sums(bundle);return {"status":"offline-release-qualified","root_sha256":root,"files":sum(1 for p in bundle.rglob("*") if p.is_file()),"artifacts":manifest,"database":db}
def main(argv:Iterable[str]|None=None)->int:
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--bundle",required=True,type=Path);parser.add_argument("--raw-dir",required=True,type=Path);parser.add_argument("--tool-verification",required=True,type=Path);parser.add_argument("--database-status",required=True,type=Path);args=parser.parse_args(argv)
 try:print(json.dumps(qualify(bundle=args.bundle,raw_dir=args.raw_dir,tool_verification=args.tool_verification,database_status=args.database_status),ensure_ascii=True,sort_keys=True));return 0
 except (EvidenceError,OSError,ValueError,TypeError) as exc:print(json.dumps({"status":"failed","reason":str(exc)[:160]},ensure_ascii=True));return 2
if __name__=="__main__":raise SystemExit(main())
