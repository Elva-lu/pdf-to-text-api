from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF
import json
import os
from io import BytesIO

app = Flask(__name__)

# ---------- 工具 ----------

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def read_file_bytes(file_storage) -> bytes:
    file_storage.stream.seek(0)
    return file_storage.stream.read()

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() or ""
    return clean_text(text)

def ocr_space_post(data: dict, timeout=90) -> dict:
    api_key = os.environ.get("OCR_SPACE_API_KEY", "K85762331988957")
    payload = {"apikey": api_key, **data}
    r = requests.post("https://api.ocr.space/parse/image", data=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ocr_space_pdf_base64(pdf_bytes: bytes, engine=2, language="cht") -> tuple[str, dict]:
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    result = ocr_space_post({
        "language": language,
        "isOverlayRequired": False,
        "OCREngine": engine,
        # 有些情況加 filetype 會更穩
        "filetype": "PDF",
        "detectOrientation": True,
        "base64Image": f"data:application/pdf;base64,{b64}",
    })
    text = ""
    parsed = result.get("ParsedResults") or []
    if parsed:
        text = parsed[0].get("ParsedText") or ""
    return clean_text(text), result

def pdf_pages_to_png_bytes(pdf_bytes: bytes, max_pages=3, zoom=2.0) -> list[bytes]:
    """
    把 PDF 前 max_pages 頁轉成 PNG bytes
    zoom 越大越清楚，但越大越慢/越大檔
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    mat = fitz.Matrix(zoom, zoom)
    for i in range(min(len(doc), max_pages)):
        pix = doc[i].get_pixmap(matrix=mat, alpha=False)
        images.append(pix.tobytes("png"))
    return images

def ocr_space_image_base64(image_bytes: bytes, engine=2, language="cht") -> tuple[str, dict]:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    result = ocr_space_post({
        "language": language,
        "isOverlayRequired": False,
        "OCREngine": engine,
        "detectOrientation": True,
        "base64Image": f"data:image/png;base64,{b64}",
    })
    text = ""
    parsed = result.get("ParsedResults") or []
    if parsed:
        text = parsed[0].get("ParsedText") or ""
    return clean_text(text), result

# ✅ 直接從檔名抓怨訴編號（不 OCR）
def extract_complaint_id_from_filename(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    name = re.sub(r"[\s._-]+", "", name)
    m = re.search(r"([A-Z]{2}\d{5,})", name, re.IGNORECASE)
    return m.group(1).upper() if m else ""

# ---------- 結構化解析 (TFDA 相關) ----------

def extract_case_id(text):
    match = re.search(r"TW-TFDA-TDS-\d+", text)
    return match.group(0) if match else ""

def extract_patient_info(text):
    return {
        "id": re.search(r"識別代號\s*(\S+)", text).group(1) if re.search(r"識別代號\s*(\S+)", text) else "",
        "gender": re.search(r"性別\s*(男|女|未知)", text).group(1) if re.search(r"性別\s*(男|女|未知)", text) else "",
        "weight_kg": float(re.search(r"體重\s*([\d\.]+)", text).group(1)) if re.search(r"體重\s*([\d\.]+)", text) else None,
        "height_cm": float(re.search(r"身高\s*([\d\.]+)", text).group(1)) if re.search(r"身高\s*([\d\.]+)", text) else None,
        "age": int(re.search(r"(\d+)\s*歲", text).group(1)) if re.search(r"(\d+)\s*歲", text) else None,
    }

def extract_severity_flags(text):
    severity_labels = [
        "死亡",
        "危及生命",
        "永久性殘疾",
        "胎兒、嬰兒先天性畸形",
        "病人住院或延長病人住院時間",
        "其他可能導致永久性傷害之併發症",
        "非嚴重",
    ]
    results = []
    for label in severity_labels:
        pattern = rf"(■|☑|✓|√|\[ ?[xX]?\]|\( ?[xX]?\))?\s*{re.escape(label)}"
        if re.search(pattern, text):
            results.append(label)
    return results

def extract_adverse_event(text):
    date_match = re.search(r"不良反應\s*發生\s*日期\s*(\d+年\d+月\d+日)", text)

    severity_matches = extract_severity_flags(text)
    symptoms_matches = re.findall(r"不良反應\s*症狀\s*([^\n]+)", text)

    desc_match = re.search(r"通報案件之描述\s*(.*?)\s*(相關檢查|不良反應後續結果)", text, re.DOTALL)
    description = desc_match.group(1).strip() if desc_match and desc_match.group(1) else ""

    outcome_match = re.search(
        r"不良反應後續結果\s*(已恢復已解決|恢復中解決中|尚未恢復|已恢復解決但有後遺症|死亡|未知)",
        text,
    )

    return {
        "date": date_match.group(1) if date_match else "",
        "severity": severity_matches,
        "symptoms": symptoms_matches,
        "description": description,
        "outcome": outcome_match.group(1) if outcome_match else "",
    }

def extract_lab_results(text):
    pattern = r"(\d{3,4}年\d{1,2}月\d{1,2}日)[^\n]*?([A-Za-z0-9\(\)/]+)[^\n]*?[=:]\s*([\d\.]+[^\s\n]*)"
    matches = re.findall(pattern, text)
    return [{"date": d, "item": i.strip(), "value": v.strip()} for d, i, v in matches]

def extract_drugs(text):
    blocks = re.findall(r"(商品名/學名[:：]?.*?)(?=商品名/學名[:：]?|$)", text, re.DOTALL)
    drugs = []

    def clean_quotes(val):
        return re.sub(r"[\"']", " ", val) if val else val

    for block in blocks:
        block = re.sub(r"[\"']", " ", block)
        drugs.append({
            "license": clean_quotes(re.search(r"許可證字號[:：]?\s*(\S+)", block).group(1)) if re.search(r"許可證字號[:：]?\s*(\S+)", block) else "",
            "name": clean_quotes(re.search(r"商品名/學名[:：]?\s*([^\n]+)", block).group(1).strip()) if re.search(r"商品名/學名[:：]?\s*([^\n]+)", block) else "",
            "dosage": clean_quotes(re.search(r"劑量[:：]?\s*([^\n]+)", block).group(1).strip()) if re.search(r"劑量[:：]?\s*([^\n]+)", block) else "",
            "route": clean_quotes(re.search(r"用法[:：]?\s*([^\n]+)", block).group(1).strip()) if re.search(r"用法[:：]?\s*([^\n]+)", block) else "",
            "start_date": re.search(r"開始日期[:：]?\s*(\d+年\d+月\d+日)", block).group(1) if re.search(r"開始日期[:：]?\s*(\d+年\d+月\d+日)", block) else "",
            "end_date": re.search(r"結束日期[:：]?\s*(\d+年\d+月\d+日)", block).group(1) if re.search(r"結束日期[:：]?\s*(\d+年\d+月\d+日)", block) else "",
            "indication": clean_quotes(re.search(r"(?:用藥原因|用途原因)[:：]?\s*([^\n]+)", block).group(1).strip()) if re.search(r"(?:用藥原因|用途原因)[:：]?\s*([^\n]+)", block) else "",
            "manufacturer": clean_quotes(re.search(r"(?:廠牌|藥廠|副作用|批號)[:：]?\s*([^\n]+)", block).group(1).strip()) if re.search(r"(?:廠牌|藥廠|副作用|批號)[:：]?\s*([^\n]+)", block) else "",
            "action": re.search(r"(停藥|降低劑量|增加劑量|未改變劑量|未知)", block).group(1) if re.search(r"(停藥|降低劑量|增加劑量|未改變劑量|未知)", block) else "",
            "rechallenge": re.search(r"(有再投予且不良反應發生|有再投予但不良反應未發生|有再投予但結果未知|沒有再投予或未知)", block).group(1) if re.search(r"(有再投予且不良反應發生|有再投予但不良反應未發生|有再投予但結果未知|沒有再投予或未知)", block) else "",
            "relation": {
                "suspected": "可疑藥品" in block,
                "concomitant": "併用產品" in block,
                "interaction": "交互作用藥品" in block,
            },
        })

    return drugs

def extract_medical_history(text):
    block_match = re.search(r"其他相關資訊.*?(\(請提供.*?\))?(.*?)用藥原因", text, re.DOTALL)
    block = block_match.group(2).strip() if block_match else ""

    diagnosis = re.findall(r"診斷\d*[:：]?\s*([^\[#\n]+)", block)
    allergy = re.search(r"過敏[:：]?\s*([^\[#\n]+)", block)
    smoking = re.search(r"(吸菸|飲酒)[^\n]*?(無|有)", block)
    liver_kidney = re.search(r"(肝|腎)[^\n]*?(功能)?[^\n]*?(正常|異常|NA|無)", block)

    return {
        "diagnosis": [d.strip() for d in diagnosis] if diagnosis else [],
        "allergy": allergy.group(1).strip() if allergy else "無",
        "smoking_alcohol": smoking.group(2) if smoking else "無",
        "liver_kidney_function": liver_kidney.group(3) if liver_kidney else "未知",
    }

# ---------- API ----------

@app.route("/extract-text", methods=["POST"])
def extract_text():
    files = (
        request.files.getlist("file")
        or request.files.getlist("files")
        or request.files.getlist("files[]")
    )
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    results = []

    for file in files:
        if not file or file.filename == "":
            continue

        try:
            filename = file.filename
            raw_text = ""
            part_number = None
            structured_json = None

            debug = {
                "used_pymupdf": False,
                "used_ocr_pdf": False,
                "used_ocr_images": False,
                "pymupdf_len": 0,
                "ocr_pdf_len": 0,
                "ocr_images_len": 0,
                "ocr_pdf_error": None,
                "ocr_images_error": None,
            }

            if filename.startswith("C"):
                extracted_complaint = extract_complaint_id_from_filename(filename)
                structured_json = {"part_number": "", "complaint_id": extracted_complaint}
                part_number = f"怨訴編號: {extracted_complaint}" if extracted_complaint else "[No complaint ID found]"

            elif filename.startswith("TW-TFDA"):
                pdf_bytes = read_file_bytes(file)

                # 1) PyMuPDF 抽文字層
                debug["used_pymupdf"] = True
                raw_text = extract_text_from_pdf_bytes(pdf_bytes)
                debug["pymupdf_len"] = len(raw_text)

                # 2) 不夠就 OCR（PDF base64）
                if len(raw_text) < 80:
                    debug["used_ocr_pdf"] = True
                    try:
                        ocr_text, ocr_resp = ocr_space_pdf_base64(pdf_bytes, engine=2, language="cht")
                        debug["ocr_pdf_len"] = len(ocr_text)
                        # OCR.space 如果處理失敗通常會有錯誤欄位
                        if ocr_resp.get("IsErroredOnProcessing"):
                            debug["ocr_pdf_error"] = ocr_resp.get("ErrorMessage") or ocr_resp.get("ErrorDetails") or "IsErroredOnProcessing=true"
                        if ocr_text:
                            raw_text = ocr_text
                    except Exception as e:
                        debug["ocr_pdf_error"] = str(e)

                # 3) OCR(PDF) 還是空 → 轉圖片 OCR
                if len(raw_text) < 80:
                    debug["used_ocr_images"] = True
                    try:
                        page_imgs = pdf_pages_to_png_bytes(pdf_bytes, max_pages=3, zoom=2.0)
                        parts = []
                        for img in page_imgs:
                            t, resp = ocr_space_image_base64(img, engine=2, language="cht")
                            if resp.get("IsErroredOnProcessing"):
                                debug["ocr_images_error"] = resp.get("ErrorMessage") or resp.get("ErrorDetails") or "IsErroredOnProcessing=true"
                            if t:
                                parts.append(t)
                        joined = clean_text(" ".join(parts))
                        debug["ocr_images_len"] = len(joined)
                        if joined:
                            raw_text = joined
                    except Exception as e:
                        debug["ocr_images_error"] = str(e)

                structured_json = {
                    "case_id": extract_case_id(raw_text),
                    "reporter": {},
                    "patient": extract_patient_info(raw_text),
                    "adverse_event": extract_adverse_event(raw_text),
                    "medical_history": extract_medical_history(raw_text),
                    "lab_results": extract_lab_results(raw_text),
                    "drugs": extract_drugs(raw_text),
                }
                part_number = "[TFDA structured JSON]"

            else:
                raw_text = "[Unsupported filename format]"
                part_number = "[Unsupported filename format]"
                structured_json = {}
                debug = {"note": "Unsupported filename format"}

            results.append({
                "filename": filename,
                "part_number": part_number,
                "raw_text": raw_text,
                "structured_json": json.dumps(structured_json, ensure_ascii=False) if isinstance(structured_json, dict) else structured_json,
                "debug": debug,  # ✅ 你在 Make 直接看到問題點
            })

        except Exception as e:
            results.append({"filename": file.filename, "error": str(e)})

    return app.response_class(
        response=json.dumps(results, ensure_ascii=False),
        status=200,
        mimetype="application/json",
    )

if __name__ == "__main__":
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
