# -*- coding: utf-8 -*-
"""
Equation Modal Processor.

Layer: Core
Primary Responsibility: EquationModalProcessor — LLM-based equation/LaTeX analysis,
    variable identification, formula explanation.
Key Dependencies: raganything.prompt (PROMPTS), raganything.utils (equation helpers)
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
from raganything.utils import get_equation_text_and_format


class EquationModalProcessor(BaseModalProcessor):
    """Processor specialized for equation content"""

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
        Generate equation description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.
        """
        try:
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"equation": modal_content}
            else:
                content_data = modal_content

            equation_text, equation_format = get_equation_text_and_format(content_data)
            language = get_multimodal_prompt_language()
            prompts = get_multimodal_prompts(language)
            default_entity_name = (
                "为该公式生成唯一且语义明确的中文名称"
                if language == "zh"
                else "descriptive name for this equation"
            )

            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            if context:
                equation_prompt = prompts.get(
                    "equation_prompt_with_context", prompts["equation_prompt"]
                ).format(
                    context=context,
                    equation_text=equation_text,
                    equation_format=equation_format,
                    entity_name=entity_name
                    if entity_name
                    else default_entity_name,
                )
            else:
                equation_prompt = prompts["equation_prompt"].format(
                    equation_text=equation_text,
                    equation_format=equation_format,
                    entity_name=entity_name
                    if entity_name
                    else default_entity_name,
                )

            response = await self._call_modal_caption(
                equation_prompt,
                system_prompt=prompts["EQUATION_ANALYSIS_SYSTEM"],
            )

            enhanced_caption, entity_info = self._parse_equation_response(
                response, entity_name
            )
            return enhanced_caption, entity_info

        except Exception as e:
            logger.error(f"Error generating equation description: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"equation_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "equation",
                "summary": f"Equation content: {str(modal_content)[:100]}",
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
        """Process equation content with context support"""
        try:
            enhanced_caption, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"equation": modal_content}
            else:
                content_data = modal_content

            equation_text, equation_format = get_equation_text_and_format(content_data)
            prompts = get_multimodal_prompts()

            modal_chunk = prompts["equation_chunk"].format(
                equation_text=equation_text,
                equation_format=equation_format,
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
            logger.error(f"Error processing equation content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"equation_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "equation",
                "summary": f"Equation content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity, []

    def _parse_equation_response(
        self, response: str, entity_name: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse equation analysis response with robust JSON handling"""
        try:
            return self._parse_typed_response(response, entity_name, "equation")
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logger.error(f"Error parsing equation analysis response: {e}")
            logger.debug(f"Raw response: {response}")
            cleaned = self._strip_thinking_tags(response)
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"equation_{compute_mdhash_id(cleaned)}",
                "entity_type": "equation",
                "summary": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            }
            return cleaned, fallback_entity


__all__ = ["EquationModalProcessor"]
