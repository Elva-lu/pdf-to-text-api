from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF

app = Flask(__name__)

# ---------- 共用工具 ----------

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_text_from_pdf(file_stream):
    file_stream.seek(0)
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return clean_text(text)

# ---------- OCR 模組 ----------

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
    match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
    return match.group(1) if match else None

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

def extract_adverse_event(text):
    return {
        "date": re.search(r'不良反應發生日期\s*(\d+年\d+月\d+日)', text).group(1) if re.search(r'不良反應發生日期\s*(\d+年\d+月\d+日)', text) else "",
        "severity": re.findall(r'不良反應嚴重性\s*(死亡|危及生命|永久性殘疾|住院|非嚴重|其他)', text),
        "symptoms": re.findall(r'不良反應症狀\s*([^\n]+)', text),
        "description": re.search(r'通報案件之描述\s*(.*?)相關檢查', text).group(1).strip() if re.search(r'通報案件之描述\s*(.*?)相關檢查', text) else "",
        "outcome": re.search(r'不良反應後續結果\s*(已恢復|尚未恢復|死亡|未知)', text).group(1) if re.search(r'不良反應後續結果\s*(已恢復|尚未恢復|死亡|未知)', text) else ""
    }

def extract_lab_results(text):
    matches = re.findall(r'(\d+年\d+月\d+日)\s*(\S+)\s*=\s*([\d\.]+[^ \n]*)', text)
    return [{"date": d, "item": i, "value": v} for d, i, v in matches]

def extract_drugs(text):
    blocks = re.findall(r'許可證字號\s*(.*?)再投藥是否出現同樣反應', text)
    drugs = []
    for block in blocks:
        drugs.append({
            "license": re.search(r'衛署藥(?:製|輸|販)字第\s*(\S+)', block).group(1) if re.search(r'衛署藥(?:製|輸|販)字第\s*(\S+)', block) else "",
            "name": re.search(r'商品名(?:/學名)?\s*(\S+)', block).group(1) if re.search(r'商品名(?:/學名)?\s*(\S+)', block) else "",
            "route": re.search(r'給藥途徑\s*(\S+)', block).group(1) if re.search(r'給藥途徑\s*(\S+)', block) else "",
            "dosage": re.search(r'劑量/頻率\s*(\S+)', block).group(1) if re.search(r'劑量/頻率\s*(\S+)', block) else "",
            "start_date": re.search(r'起迄日期\s*(\d+年\d+月\d+日)', block).group(1) if re.search(r'起迄日期\s*(\d+年\d+月\d+日)', block) else "",
            "end_date": re.search(r'迄日期\s*(\d+年\d+月\d+日)', block).group(1) if re.search(r'迄日期\s*(\d+年\d+月\d+日)', block) else "",
            "indication": re.search(r'用藥原因\s*(\S+)', block).group(1) if re.search(r'用藥原因\s*(\S+)', block) else "",
            "manufacturer": re.search(r'廠牌\s*(\S+)', block).group(1) if re.search(r'廠牌\s*(\S+)', block) else "",
            "action": re.search(r'處置情形\s*(停藥|減量|增加|未改變|未知)', block).group(1) if re.search(r'處置情形\s*(停藥|減量|增加|未改變|未知)', block) else "",
            "rechallenge": re.search(r'再投藥是否出現同樣反應\s*(.*?)\s', block).group(1) if re.search(r'再投藥是否出現同樣反應\s*(.*?)\s', block) else ""
        })
    return drugs

# ---------- API ----------

@app.route('/extract-text', methods=['POST'])
def extract_text():
    files = request.files.getlist('file') or request.files.getlist('files') or request.files.getlist('files[]')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    results = []

    for file in files:
        if not file or file.filename == '':
            continue

        filename = file.filename
        raw_text = ""
        part_number = None
        structured_json = None

        try:
            if filename.startswith("C"):
                raw_text = ocr_space_api_base64(file.stream)
                extracted = extract_part_number_from_text(raw_text)
                part_number = f"料品號：{extracted}" if extracted else "[No part number found]"

            elif filename.startswith("TW-TFDA"):
                raw_text = extract_text_from_pdf(file.stream)
                structured_json = {
                    "case_id": extract_case_id(raw_text),
                    "reporter": {},
                    "patient": extract_patient_info(raw_text),
                    "adverse_event": extract_adverse_event(raw_text),
                    "medical_history": {},
                    "lab_results": extract_lab_results(raw_text),
                    "drugs": extract_drugs(raw_text),
                    "raw_text": raw_text
                }
                part_number = "[TFDA structured JSON]"

            else:
                raw_text = "[Unsupported filename format]"
                part_number = "[Unsupported filename format]"

            results.append({
                'filename': filename,
                'part_number': part_number,
                'raw_text': raw_text,
                'structured_json': structured_json
            })

        except Exception as e:
            results.append({
                'filename': filename,
                'error': str(e)
            })

    return jsonify(results)

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
