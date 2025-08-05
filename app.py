from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF

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
    match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
    return match.group(1) if match else None

# ---------- 結構化解析 ----------

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
    date_match = re.search(r'不良反應發生日期\s*(\d+年\d+月\d+日)', text)
    severity_matches = re.findall(r'不良反應嚴重性\s*(死亡|危及生命|永久性殘疾|胎兒、嬰兒先天性畸形|病人住院或延長病人住院時間|其他可能導致永久性傷害之併發症|非嚴重)', text)
    symptoms_matches = re.findall(r'不良反應症狀\s*([^\n]+)', text)
    desc_match = re.search(r'通報案件之描述\s*(.*?)\s*(相關檢查|不良反應後續結果)', text)
    description = desc_match.group(1).strip() if desc_match else ""
    outcome_match = re.search(r'不良反應後續結果\s*(已恢復已解決|恢復中解決中|尚未恢復|已恢復解決但有後遺症|死亡|未知)', text)

    return {
        "date": date_match.group(1) if date_match else "",
        "severity": severity_matches,
        "symptoms": symptoms_matches,
        "description": description,
        "outcome": outcome_match.group(1) if outcome_match else ""
    }

def extract_lab_results(text):
    pattern = r'(\d{3,4}年\d{1,2}月\d{1,2}日)[^\n]*?([A-Za-z0-9\(\)/]+)[^\n]*?[=:]\s*([\d\.]+[^\s\n]*)'
    matches = re.findall(pattern, text)
    return [{"date": d, "item": i.strip(), "value": v.strip()} for d, i, v in matches]

def extract_drugs(text):
    # 分段：每筆藥物資料以商品名/學名開頭
    blocks = re.findall(r'(商品名/學名[:：]?.*?)(?=商品名/學名[:：]?|$)', text, re.DOTALL)
    drugs = []

    def clean_quotes(val):
        return val.replace('"', "'") if val else val

    for block in blocks:
        block = block.replace('"', "'")  # ← ✅ 清整段 block 的雙引號

        drugs.append({
            "license": clean_quotes(re.search(r'許可證字號[:：]?\s*(\S+)', block).group(1)) if re.search(r'許可證字號[:：]?\s*(\S+)', block) else "",
            "name": clean_quotes(re.search(r'商品名/學名[:：]?\s*([^\n]+)', block).group(1).strip()) if re.search(r'商品名/學名[:：]?\s*([^\n]+)', block) else "",
            "dosage": clean_quotes(re.search(r'劑量[:：]?\s*([^\n]+)', block).group(1).strip()) if re.search(r'劑量[:：]?\s*([^\n]+)', block) else "",
            "route": clean_quotes(re.search(r'用法[:：]?\s*([^\n]+)', block).group(1).strip()) if re.search(r'用法[:：]?\s*([^\n]+)', block) else "",
            "start_date": re.search(r'開始日期[:：]?\s*(\d+年\d+月\d+日)', block).group(1) if re.search(r'開始日期[:：]?\s*(\d+年\d+月\d+日)', block) else "",
            "end_date": re.search(r'結束日期[:：]?\s*(\d+年\d+月\d+日)', block).group(1) if re.search(r'結束日期[:：]?\s*(\d+年\d+月\d+日)', block) else "",
            "indication": clean_quotes(re.search(r'(?:用藥原因|用途原因)[:：]?\s*([^\n]+)', block).group(1).strip()) if re.search(r'(?:用藥原因|用途原因)[:：]?\s*([^\n]+)', block) else "",
            "manufacturer": clean_quotes(re.search(r'(?:廠牌|藥廠|副作用|批號)[:：]?\s*([^\n]+)', block).group(1).strip()) if re.search(r'(?:廠牌|藥廠|副作用|批號)[:：]?\s*([^\n]+)', block) else "",
            "action": re.search(r'(停藥|降低劑量|增加劑量|未改變劑量|未知)', block).group(1) if re.search(r'(停藥|降低劑量|增加劑量|未改變劑量|未知)', block) else "",
            "rechallenge": re.search(r'(有再投予且不良反應發生|有再投予但不良反應未發生|有再投予但結果未知|沒有再投予或未知)', block).group(1) if re.search(r'(有再投予且不良反應發生|有再投予但不良反應未發生|有再投予但結果未知|沒有再投予或未知)', block) else "",
            "relation": {
                "suspected": "可疑藥品" in block,
                "concomitant": "併用產品" in block,
                "interaction": "交互作用藥品" in block
            }
        })

    return drugs

def extract_medical_history(text):
    block_match = re.search(r'其他相關資訊.*?(\(請提供.*?\))?(.*?)用藥原因', text)
    block = block_match.group(2).strip() if block_match else ""
    diagnosis = re.findall(r'診斷\d*[:：]?\s*([^\[#\\n]+)', block)
    allergy = re.search(r'過敏[:：]?\s*([^\[#\\n]+)', block)
    smoking = re.search(r'(吸菸|飲酒)[^\n]*?(無|有)', block)
    liver_kidney = re.search(r'(肝|腎)[^\n]*?(功能)?[^\n]*?(正常|異常|NA|無)', block)

    return {
        "diagnosis": diagnosis if diagnosis else [],
        "allergy": allergy.group(1).strip() if allergy else "無",
        "smoking_alcohol": smoking.group(2) if smoking else "無",
        "liver_kidney_function": liver_kidney.group(3) if liver_kidney else "未知"
    }

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

        try:
            filename = file.filename
            raw_text = ""
            part_number = None
            structured_json = None

            if filename.startswith("C"):
                raw_text = ocr_space_api_base64(file.stream)
                extracted = extract_part_number_from_text(raw_text)
                part_number = f"料號識別: {extracted}" if extracted else "[No part number found]"

                structured_json = {
                    "part_number": extracted if extracted else ""
                }

            elif filename.startswith("TW-TFDA"):
                raw_text = extract_text_from_pdf(file.stream)
                structured_json = {
                    "case_id": extract_case_id(raw_text),
                    "reporter": {},
                    "patient": extract_patient_info(raw_text),
                    "adverse_event": extract_adverse_event(raw_text),
                    "medical_history": extract_medical_history(raw_text),
                    "lab_results": extract_lab_results(raw_text),
                    "drugs": extract_drugs(raw_text)
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
                'filename': file.filename,
                'error': str(e)
            })

    import json
    for item in results:
        if "structured_json" in item and isinstance(item["structured_json"], dict):
            item["structured_json"] = json.dumps(item["structured_json"], ensure_ascii=False)

return app.response_class(
    response=json.dumps(results, ensure_ascii=False),  # 👈 確保中文不被轉義成 \uXXXX
    status=200,
    mimetype='application/json'
)

# ---------- 啟動 Flask ----------
if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
