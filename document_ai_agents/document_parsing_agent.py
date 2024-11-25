import json
from pathlib import Path
from typing import Literal

import google.generativeai as genai
from langchain_core.documents import Document
from pydantic import BaseModel, Field

from document_ai_agents.document_utils import extract_images_from_pdf
from document_ai_agents.image_utils import pil_image_to_base64_png
from document_ai_agents.logger import logger
from document_ai_agents.schema_utils import prepare_schema_for_gemini


class DetectedLayoutItem(BaseModel):
    element_type: Literal["Table", "Figure", "Image", "Text-block"] = Field(
        ...,
        description="Type of detected Item. Find Tables, figures and images. Use Text-Block for everything else, "
        "be as exhaustive as possible. Return 10 Items at most.",
    )
    summary: str = Field(..., description="A detailed description of the layout Item.")


class LayoutElements(BaseModel):
    layout_items: list[DetectedLayoutItem] = []


class DocumentLayoutParsingState(BaseModel):
    document_path: str
    pages_as_base64_png_images: list[str] = []
    documents: list[Document] = []


class FindLayoutItems(BaseModel):
    base64_png: str
    page_number: int


class DocumentParsingAgent:
    def __init__(self, model_name="gemini-1.5-flash-002"):
        layout_elements_schema = prepare_schema_for_gemini(LayoutElements)

        logger.info(f"Using Gemini model with schema: {layout_elements_schema}")
        self.model_name = model_name
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": layout_elements_schema,
            },
        )
        self.agent = None

    @classmethod
    def get_images(cls, state: DocumentLayoutParsingState):
        assert Path(state.document_path).is_file(), "File does not exist"

        images = extract_images_from_pdf(state.document_path)

        assert images, "No images extracted"

        pages_as_base64_png_images = [pil_image_to_base64_png(x) for x in images]

        return {"pages_as_base64_png_images": pages_as_base64_png_images}

    def find_layout_items(self, state: DocumentLayoutParsingState):
        documents = []
        for i, base64_image_page in enumerate(state.pages_as_base64_png_images):
            logger.info(
                f"Processing page {i + 1}/{len(state.pages_as_base64_png_images)}"
            )
            messages = [
                f"Find and summarize all the relevant layout elements in this pdf page in the following format: "
                f"{LayoutElements.model_json_schema()}. "
                f"Tables should have at least two columns and at least two rows. "
                f"The coordinates should overlap with each layout item.",
                {"mime_type": "image/png", "data": base64_image_page},
            ]

            result = self.model.generate_content(messages)
            data = json.loads(result.text)
            documents.extend(
                [
                    Document(
                        page_content=x["summary"],
                        metadata={
                            "page_number": i,
                            "element_type": x["element_type"],
                        },
                    )
                    for x in data["layout_items"]
                ]
            )
            logger.info(
                f"Extracted {len(data['layout_items'])} layout elements from page {i + 1}."
            )

        logger.info(f"Total layout elements extracted: {len(documents)}")
        return {"documents": documents}


if __name__ == "__main__":
    _state = DocumentLayoutParsingState(
        document_path=str(Path(__file__).parents[1] / "data" / "docs.pdf")
    )

    agent = DocumentParsingAgent()

    result_node1 = agent.get_images(_state)
    _state.pages_as_base64_png_images = result_node1["pages_as_base64_png_images"]
    result_node2 = agent.find_layout_items(_state)

    for item in result_node2["documents"]:
        print(item.page_content)
        print(item.metadata["element_type"])