# OpenDataLoader PDF 2.5.0 合同探针

此探针验证固定 SDK 的本地逐页工件合同，不是质量基准或发布许可。它生成一个不含业务数据的五页 PDF：列表、表格、图片、公式文本与空白页；随后对每一页单独调用官方 `opendataloader_pdf.convert()`。

请在具备 JRE 17 与 `opendataloader-pdf==2.5.0` 的环境执行：

```powershell
$env:JAVA_HOME = 'D:\Java\jre17\jdk-17.0.19+10-jre'
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
python scripts\opendataloader_contract_probe.py --output $env:TEMP\odl-contract
```

输出目录必须为空。`contract-report.json` 只记录 SDK/Java 版本、输入哈希、固定选项、相对工件名与哈希、元素类型、字段名、页标记、原始 bbox 值，以及损坏和加密 PDF 的本地预检结果。不要提交该目录内的原始 JSON、Markdown 或媒体。

2026-07-27 在 Windows、Temurin JRE 17.0.19 与 SDK 2.5.0 的实际运行中，每个单页请求各生成一个 JSON 与一个 Markdown；第 1 页包含 `list`/`list item`，第 2 页包含 `table`，第 3 页包含 `image`，第 4 页的公式文本为 `paragraph`，第 5 页为 `kids=[]`，其 Markdown 的 SHA-256 为空字节串的哈希。探针测试会同时验证各页的合成文本标记、产物唯一性和相对目录。

报告中的 bbox 仅为 SDK 返回的原始四个数值。该探针不声称其单位、坐标轴原点或数组字段顺序；任何依赖这些语义的适配器逻辑都必须另有 SDK 文档或独立验证。

损坏 PDF 在本地 `pypdf` 预检中报 `PdfStreamError`，加密 PDF 报 `FileNotDecryptedError`；适配器将这类读取失败归类为 `odl_preflight`。逐页策略是覆盖证明：不得从批量 JSON 缺失元素推断空白页。它也不替代 30–50 份获批 staging 语料的质量与资源评测。
