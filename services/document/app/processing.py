"""Real text extraction in a bounded child process. No OCR, HTML or network."""

import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile

from defusedxml import ElementTree as SafeXML

MAX_TEXT = 8 * 1024 * 1024
MAX_LOCATORS = 5000
MAX_EXPANDED = 128 * 1024 * 1024
MAX_ENTRIES = 2000


class ProcessingError(ValueError):
    pass


def text_sections(text: str) -> list[str]:
    # Text sections, not invented physical PDF/Word pages.
    sections = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    result = []
    for section in sections:
        for start in range(0, len(section), 12000):
            result.append(section[start : start + 12000])
    return result


def zip_text(path: Path, format_: str) -> list[str]:
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES or sum(i.file_size for i in entries) > MAX_EXPANDED:
            raise ProcessingError("EXPANSION_LIMIT")
        names = [i.filename for i in entries]
        if len(names) != len(set(names)) or any(
            name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/")
            for name in names
        ):
            raise ProcessingError("INVALID_ARCHIVE")
        if format_ == "DOCX":
            if "word/document.xml" not in names:
                raise ProcessingError("INVALID_FORMAT")
            root = SafeXML.fromstring(archive.read("word/document.xml"), forbid_dtd=True)
            paragraphs = []
            for paragraph in root.iter():
                if paragraph.tag.endswith("}p"):
                    paragraphs.append(
                        "".join(
                            node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")
                        )
                    )
            return text_sections("\n\n".join(paragraphs))
        if "ppt/presentation.xml" not in names:
            raise ProcessingError("INVALID_FORMAT")
        # Presentation order comes from relationships, not the slide filename number.
        presentation = SafeXML.fromstring(archive.read("ppt/presentation.xml"), forbid_dtd=True)
        relations = SafeXML.fromstring(
            archive.read("ppt/_rels/presentation.xml.rels"), forbid_dtd=True
        )
        targets = {}
        for node in relations:
            target = node.attrib.get("Target", "")
            if node.attrib.get("TargetMode") == "External":
                continue
            if re.fullmatch(r"slides/slide[0-9]+\.xml", target):
                targets[node.attrib.get("Id")] = "ppt/" + target
        pages = []
        for slide in presentation.iter():
            if not slide.tag.endswith("}sldId"):
                continue
            reference = next((v for k, v in slide.attrib.items() if k.endswith("}id")), None)
            target = targets.get(reference)
            if target is None or target not in names:
                raise ProcessingError("INVALID_FORMAT")
            root = SafeXML.fromstring(archive.read(target), forbid_dtd=True)
            pages.append(
                "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
            )
        return pages


def extract(path: Path, format_: str) -> list[dict]:
    try:
        if format_ == "PDF":
            from pypdf import PdfReader

            if path.open("rb").read(5) != b"%PDF-":
                raise ProcessingError("INVALID_FORMAT")
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise ProcessingError("ENCRYPTED_PDF")
            if len(reader.pages) > MAX_LOCATORS:
                raise ProcessingError("CONTENT_LIMIT")
            texts = []
            text_bytes = 0
            for page in reader.pages:
                value = page.extract_text() or ""
                text_bytes += len(value.encode("utf-8"))
                if text_bytes > MAX_TEXT:
                    raise ProcessingError("CONTENT_LIMIT")
                texts.append(value)
        elif format_ in {"DOCX", "PPTX"}:
            texts = zip_text(path, format_)
        elif format_ in {"TXT", "MD"}:
            value = path.read_bytes().decode("utf-8-sig", errors="strict")
            if "\x00" in value:
                raise ProcessingError("INVALID_FORMAT")
            texts = text_sections(value)
        else:
            raise ProcessingError("INVALID_FORMAT")
        if not any(text.strip() for text in texts):
            raise ProcessingError("NO_EXTRACTABLE_TEXT")
        if len(texts) > MAX_LOCATORS or sum(len(s.encode("utf-8")) for s in texts) > MAX_TEXT:
            raise ProcessingError("CONTENT_LIMIT")
        label = "Trang" if format_ == "PDF" else "Slide" if format_ == "PPTX" else "Mục"
        return [
            {"id": str(i), "number": i, "title": f"{label} {i}", "text": value}
            for i, value in enumerate(texts, 1)
        ]
    except ProcessingError:
        raise
    except MemoryError:
        raise
    except Exception as error:
        # Parser exception details may contain paths or source text: never persist them.
        raise ProcessingError("INVALID_FORMAT") from error


def main():
    # Linux container: cap the extractor itself; API process remains available.
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    try:
        result = {"content": extract(Path(sys.argv[1]), sys.argv[2])}
    except MemoryError:
        result = {"error": "RESOURCE_LIMIT"}
    except ProcessingError as error:
        result = {"error": str(error)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
