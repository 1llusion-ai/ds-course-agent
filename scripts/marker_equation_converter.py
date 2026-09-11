"""Marker converter that OCRs equations while preserving the PDF text layer."""

from __future__ import annotations

from marker.builders.document import DocumentBuilder
from marker.builders.line import LineBuilder
from marker.builders.ocr import OcrBuilder
from marker.builders.structure import StructureBuilder
from marker.converters.pdf import PdfConverter
from marker.processors.equation import EquationProcessor
from marker.providers.registry import provider_from_filepath
from marker.schema.document import Document


class EquationOcrPdfConverter(PdfConverter):
    """Run Marker processors with page/text OCR disabled and equation OCR enabled."""

    def build_document(self, filepath: str) -> Document:
        """Build a document whose existing text remains untouched by OCR."""
        provider_cls = provider_from_filepath(filepath)
        layout_builder = self.resolve_dependencies(self.layout_builder_class)
        line_builder = self.resolve_dependencies(LineBuilder)
        ocr_builder = self.resolve_dependencies(OcrBuilder)

        # These are separate instances from EquationProcessor. Disabling OCR on
        # them keeps the embedded text layer while equation blocks still use OCR.
        line_builder.disable_ocr = True
        document_builder = DocumentBuilder(self.config)
        document_builder.disable_ocr = True

        provider = provider_cls(filepath, self.config)
        document = document_builder(provider, layout_builder, line_builder, ocr_builder)
        structure_builder = self.resolve_dependencies(StructureBuilder)
        structure_builder(document)

        for processor in self.processor_list:
            if not isinstance(processor, EquationProcessor) and hasattr(processor, "disable_ocr"):
                processor.disable_ocr = True
            processor(document)
        return document
