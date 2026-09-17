# -*- coding: utf-8 -*-
"""
Table Modal Processor.

Layer: Core
Primary Responsibility: TableModalProcessor — LLM-based table analysis,
    caption generation, entity extraction from tabular data.
Key Dependencies: raganything.prompt (PROMPTS), raganything.utils (formatting)
"""

import json
from typing import Dict, Any, Tuple

from lightrag.utils import logger, compute_mdhash_id
from lightrag.lightrag import LightRAG

from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.context import ContextExtractor
from raganything.prompt_manager import (
    get_multimodal_prompt_language,
    get_multimodal_prompts,
)
from raganything.utils import (
    format_table_body,
    get_table_body,
    has_meaningful_table_content,
    normalize_caption_list,
)


class TableModalProcessor(BaseModalProcessor):
    """Processor specialized for table content"""

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
        doc_id: str = None,
        file_path: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate table description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.
        """
        try:
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"table_body": modal_content}
            else:
                content_data = modal_content

            table_img_path = content_data.get("img_path")
            table_caption = normalize_caption_list(content_data.get("table_caption"))
            table_body = format_table_body(get_table_body(content_data))
            table_footnote = normalize_caption_list(content_data.get("table_footnote"))
            language = get_multimodal_prompt_language()
            prompts = get_multimodal_prompts(language)
            missing = "无" if language == "zh" else "None"

            if not has_meaningful_table_content(content_data):
                description = (
                    "该表格未提取到可识别的单元格文本或数据，未生成具体内容分析。"
                    if language == "zh"
                    else "No recognizable cell text or data was extracted from this table."
                )
                resolved_name = (
                    entity_name
                    or (table_caption[0] if table_caption else None)
                    or ("空表格" if language == "zh" else "Empty table")
                )
                return description, {
                    "entity_name": resolved_name,
                    "entity_type": "table",
                    "summary": description,
                    "non_indexable": True,
                    "analysis_source": "empty_table",
                    "empty_reason": "no_meaningful_table_content",
                }

            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            if context:
                table_prompt = prompts.get(
                    "table_prompt_with_context", prompts["table_prompt"]
                ).format(
                    context=context,
                    entity_name=entity_name
                    if entity_name
                    else (
                        "为该表格生成唯一且语义明确的中文名称"
                        if language == "zh"
                        else "descriptive name for this table"
                    ),
                    table_img_path=table_img_path,
                    table_caption=table_caption if table_caption else missing,
                    table_body=table_body,
                    table_footnote=table_footnote if table_footnote else missing,
                )
            else:
                table_prompt = prompts["table_prompt"].format(
                    entity_name=entity_name
                    if entity_name
                    else (
                        "为该表格生成唯一且语义明确的中文名称"
                        if language == "zh"
                        else "descriptive name for this table"
                    ),
                    table_img_path=table_img_path,
                    table_caption=table_caption if table_caption else missing,
                    table_body=table_body,
                    table_footnote=table_footnote if table_footnote else missing,
                )

            response = await self._call_modal_caption(
                table_prompt,
                system_prompt=prompts["TABLE_ANALYSIS_SYSTEM"],
            )

            enhanced_caption, entity_info = self._parse_table_response(
                response, entity_name
            )
            return enhanced_caption, entity_info

        except Exception as e:
            logger.error(f"Error generating table description: {e}")
            language = get_multimodal_prompt_language()
            preview = str(modal_content)[:100]
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else (
                    f"表格_{compute_mdhash_id(str(modal_content))}"
                    if language == "zh"
                    else f"table_{compute_mdhash_id(str(modal_content))}"
                ),
                "entity_type": "table",
                "summary": (
                    f"表格内容：{preview}"
                    if language == "zh"
                    else f"Table content: {preview}"
                ),
            }
            return str(modal_content), fallback_entity

    async def process_multimodal_content(
        self,
        modal_content,
        content_type: str,
        file_path: str = "manual_creation",
        entity_name: str = None,
        item_info: Dict[str, Any] = None,
        batch_mode: bool = False,
        doc_id: str = None,
        chunk_order_index: int = 0,
    ) -> Tuple[str, Dict[str, Any]]:
        """Process table content with context support"""
        try:
            enhanced_caption, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            if isinstance(entity_info, dict) and entity_info.get("non_indexable"):
                logger.info(
                    "Skipping table content without indexable text "
                    "(source=%s, reason=%s)",
                    entity_info.get("analysis_source", "unknown"),
                    entity_info.get("empty_reason", "unknown"),
                )
                return enhanced_caption, entity_info, []

            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"table_body": modal_content}
            else:
                content_data = modal_content

            table_img_path = content_data.get("img_path")
            table_caption = normalize_caption_list(content_data.get("table_caption"))
            table_body = format_table_body(get_table_body(content_data))
            table_footnote = normalize_caption_list(content_data.get("table_footnote"))
            language = get_multimodal_prompt_language()
            prompts = get_multimodal_prompts(language)
            missing = "无" if language == "zh" else "None"
            if not has_meaningful_table_content(content_data):
                table_body = (
                    "未提取到有效表格内容。"
                    if language == "zh"
                    else "No meaningful table content was extracted."
                )

            modal_chunk = prompts["table_chunk"].format(
                table_img_path=table_img_path,
                table_caption=", ".join(table_caption) if table_caption else missing,
                table_body=table_body,
                table_footnote=", ".join(table_footnote) if table_footnote else missing,
                enhanced_caption=enhanced_caption,
            )

            return await self._create_entity_and_chunk(
                modal_chunk,
                entity_info,
                file_path,
                batch_mode,
                doc_id,
                chunk_order_index,
            )

        except Exception as e:
            logger.error(f"Error processing table content: {e}")
            language = get_multimodal_prompt_language()
            preview = str(modal_content)[:100]
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else (
                    f"表格_{compute_mdhash_id(str(modal_content))}"
                    if language == "zh"
                    else f"table_{compute_mdhash_id(str(modal_content))}"
                ),
                "entity_type": "table",
                "summary": (
                    f"表格内容：{preview}"
                    if language == "zh"
                    else f"Table content: {preview}"
                ),
            }
            return str(modal_content), fallback_entity, []

    def _parse_table_response(
        self, response: str, entity_name: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse table analysis response"""
        try:
            return self._parse_typed_response(response, entity_name, "table")
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logger.error(f"Error parsing table analysis response: {e}")
            logger.debug(f"Raw response: {response}")
            cleaned = self._strip_thinking_tags(response)
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"table_{compute_mdhash_id(cleaned)}",
                "entity_type": "table",
                "summary": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            }
            return cleaned, fallback_entity


__all__ = ["TableModalProcessor"]
