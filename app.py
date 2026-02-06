from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF
import json
import os

app = Flask(__name__)

# ---------- 工具 ----------

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def extract_text_from_pdf(file_stream):
    file_stream.seek(0)
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return clean_text(text)

def ocr_space_api_base64(file_stream, engine=2):
    file_stream.seek(0)
    base64_data = base64.b64encode(file_stream.read()).decode()
    response = requests.post(
        'https://api.ocr.space/parse/image',
        data={
            'apikey': 'K85762331988957',
            'language': 'cht',
            'isOverlayRequired': False,
            'OCREngine': engine,
            'base64Image': f'data:application/pdf;base64,{base64_data}'
        },
        timeout=30
    )
    response.raise_for_status()
    result = response.json()
    return result.get('ParsedResults', [{}])[0].get('ParsedText', '')

def extract_part_number_from_text(text):
    match = re.search(r'料品號\s*[:：]?\s*(\S+)', text)
    return match.group(1) if match else ""

# ✅【重點】直接從檔名抓怨訴編號（不走 OCR）
def extract_complaint_id_from_filename(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    name = re.sub(r'[\s._-]+', '', name)
    m = re.search(r'([A-Z]{2}\d{5,})', name, re.IGNORECASE)
    return m.group(1).upper() if m else ""

# ---------- TFDA 結構化解析 ----------

def extract_case_id(text):
    match = re.search(r'TW-TFDA-TDS-\d+', text)
    return match.group(0) if match else ""

def extract_patient_info(text):
    return {
        "id": re.search(r'識別代號\s*(\S+)', text).group(1) if re.search(r'識別代號\s*(\S+)', text) else "",
        "gender": re.search(r'性別\s*(男|女|未知)', text).group(1) if re.search(r'性別\s*(男|女|未知)', text) else "",
        "weight_kg": float(re.search(r'體重\s*([\d\.]+)', text).group(1)) if re.search(r'體重\s*([\d\.]+)', text) else None,
        "height_cm": float(re.search(r'身高\s*([\d\.]+)', text).group(1)) if re.search(r'身高\s*([\d\.]+)', text) else None,
        "age": int(re.search(r'(\d+)\s*歲', text).group(1)) if re.search(r'(\d+)\s*歲', text) else None
    }

def extract_severity_flags(text):
    labels = ["死亡", "危及生命", "永久性殘疾", "胎兒、嬰兒先天性畸形",
              "病人住院或延長病人住院時間", "其他可能導致永久性傷害之併發症", "非嚴重"]
    return [l for l in labels if l in text]

def extract_adverse_event(text):
    return {
        "date": re.search(r'不良反應發生日期\s*(\d+年\d+月\d+日)', text).group(1)
        if re.search(r'不良反應發生日期\s*(\d+年\d+月\d+日)', text) else "",
        "severity": extract_severity_flags(text)
    }

# ---------- API ----------

@app.route('/extract-text', methods=['POST'])
def extract_text():
    files = request.files.getlist('file') or request.files.getlist('files') or request.files.getlist('files[]')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    results = []

    for file in files:
        try:
            filename = file.filename
            raw_text = ""
            structured_json = {}

            # ===== C 開頭檔案：直接用檔名 =====
            if filename.startswith("C"):
                complaint_id = extract_complaint_id_from_filename(filename)

                structured_json = {
                    "part_number": "",
                    "complaint_id": complaint_id
                }

                part_number = f"怨訴編號: {complaint_id}" if complaint_id else "[No complaint ID found]"

            # ===== TFDA PDF =====
            elif filename.startswith("TW-TFDA"):
                raw_text = extract_text_from_pdf(file.stream)
                structured_json = {
                    "case_id": extract_case_id(raw_text),
                    "patient": extract_patient_info(raw_text),
                    "adverse_event": extract_adverse_event(raw_text)
                }
                part_number = "[TFDA structured JSON]"

            else:
                part_number = "[Unsupported filename format]"

            results.append({
                "filename": filename,
                "part_number": part_number,
                "raw_text": raw_text,
                "structured_json": json.dumps(structured_json, ensure_ascii=False)
            })

        except Exception as e:
            results.append({
                "filename": file.filename,
                "error": str(e)
            })

    return app.response_class(
        response=json.dumps(results, ensure_ascii=False),
        status=200,
        mimetype="application/json"
    )

# ---------- 啟動 ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
