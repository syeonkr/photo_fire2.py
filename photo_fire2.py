import os
import json
import re
import streamlit as st
import gdown
from google import genai
from PIL import Image, ImageDraw

# --- 상수 설정 ---
MAX_IMAGES = 10  # 버퍼링과 속도를 고려한 최적의 최대 이미지 개수

# --- 구글 드라이브에서 대용량 PDF 자동 다운로드 ---
file_id = "1TTEEwpUPoNIw2mrVQvRJBmSafPxHlKVk"
url = f"https://drive.google.com/uc?export=download&id={file_id}"
output = "casebook.pdf"

@st.cache_resource
def download_pdf_from_drive(drive_url, output_path):
    if not os.path.exists(output_path):
        with st.spinner("구글 드라이브에서 화재 사고 사례집 PDF를 다운로드 중입니다... 잠시만 기다려주세요!"):
            gdown.download(drive_url, output_path, quiet=False)
    return output_path

# 앱 실행 시 PDF 다운로드 수행
pdf_path = download_pdf_from_drive(url, output)
# -------------------------------------------------------------

# 페이지 기본 설정
st.set_page_config(page_title="화재사고 사례 기반 AI 분석기", layout="wide")
st.title("🔥 화재 현장 사진 기반 원인 및 발화추정지점 분석 서비스")

# 사이드바 API Key 입력창
api_key = st.sidebar.text_input("Google Gemini API Key를 입력하세요", type="password")

# 사진 업로드 UI (최대 10장 제한)
uploaded_files = st.file_uploader(
    f"화재 현장 사진을 업로드하세요 (최대 {MAX_IMAGES}장)", 
    type=["jpg", "png", "jpeg"], 
    accept_multiple_files=True
)

def resize_image(image, max_size=1024):
    """
    속도 향상 및 버퍼링 방지를 위한 이미지 리사이징 함수
    비율을 유지하며 최대 너비/높이를 max_size로 제한합니다.
    """
    img_copy = image.copy()
    img_copy.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img_copy

def draw_bounding_boxes(image, boxes):
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    width, height = img_copy.size

    for box_info in boxes:
        coords = box_info.get("box_2d", [])
        if len(coords) == 4:
            ymin, xmin, ymax, xmax = coords
            left = (xmin / 1000.0) * width
            right = (xmax / 1000.0) * width
            top = (ymin / 1000.0) * height
            bottom = (ymax / 1000.0) * height

            draw.rectangle([left, top, right, bottom], outline="red", width=5)
            
            label = box_info.get("label", "발화추정지점")
            draw.rectangle([left, max(0, top - 25), left + 120, top], fill="red")
            draw.text((left + 5, max(0, top - 20)), label, fill="white")

    return img_copy

def parse_json_from_response(text):
    try:
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception:
        return None
    return None

if uploaded_files and api_key:
    if len(uploaded_files) > MAX_IMAGES:
        st.warning(f"사진은 최대 {MAX_IMAGES}장까지만 분석 가능합니다. 처음 선택한 {MAX_IMAGES}장만 분석에 포함됩니다.")
        uploaded_files = uploaded_files[:MAX_IMAGES]

    images = []
    
    # Grid 형태로 사진 출력 (한 줄에 최대 5장씩 표시)
    cols = st.columns(min(len(uploaded_files), 5))

    for idx, file in enumerate(uploaded_files):
        img = Image.open(file)
        # 빠른 분석을 위해 최적화 리사이징 적용
        resized_img = resize_image(img)
        images.append(resized_img)
        
        with cols[idx % 5]:
            st.image(resized_img, caption=f"현장 사진 {idx+1}", use_container_width=True)

    if st.button("🔥 화재 원인 및 발화추정지점 분석 시작"):
        try:
            client = genai.Client(api_key=api_key)

            prompt = """당신은 베테랑 화재조사관을 보조하는 최고 수준의 전문 화재조사 AI 분석관입니다.
제공된 화재 현장 사진들을 매우 정밀하고 상세하게 분석하여 전문적이고 체계적인 화재감식 보고서 형식으로 작성해 주세요.

[작성 지침 및 필수 포함 내용]

1. 현장 개요 및 관찰 소견 (사진별 상세 기술):
   - 각 사진 번호별로 확인되는 소손 상태, 탄화 형태, 백화/박리 현상, 열변형 형태를 상세히 서술할 것.

2. 연소확대 경로 및 진행 방향 분석 (Fire Spread Analysis):
   - **열 전달 경로:** 대류, 복사, 전도 열 전달에 의한 연소확대 경로를 사진 속 구조물(수납장, 천장, 덕트, 배선 등)을 바탕으로 추론할 것.
   - **열흔 패턴:** V-pattern, U-pattern, 방향성 탄화 흔적, 저부 연소 흔적 등의 위치와 화열 진행 방향(상/하, 좌/우)을 분석할 것.
   - **소손 심도 구배:** 사진 간 또는 동일 영역 내 탄화 깊이(Depth of Charring) 및 용융/열변형 정도의 차이를 통해 화열의 이동 순서 및 세기를 추론할 것.

3. 발화추정지점(Point of Origin) 식별 및 근거:
   - 전체 현장에서 가장 유력한 발화지점을 사진 번호 및 구체적 위치(예: 사진 2의 수납장 내 전원 배선 접속부)로 지목하고, 열흔과 소손 심도 차이를 근거로 최소 3가지 이상 제시할 것.

4. 상태 구분 표시 (보고서 전반 준수):
   - 작성 시 내용별로 반드시 [사실], [추정], [확인 필요], [일반적 경향] 4가지 기호를 명확히 표시하여 서술할 것.

5. 원인 추론 및 법과학적 감식 제언:
   - 전기적 요인(단락, 트래킹, 접촉불량 등), 기계적 요인, 부주의 등 예상 메커니즘을 상세히 설명하고, 국과수/전문기관의 세부 감식 필요 항목(실체현미경, X-ray 분석 등)을 제언할 것.

---
[중요: 발화추정지점 좌표 출력]
보고서 맨 마지막에는 반드시 각 사진별 발화추정지점의 2D 바운딩 박스 좌표를 아래 JSON 형식 그대로 작성하세요.
상대 좌표는 0~1000 기준 [ymin, xmin, ymax, xmax] 입니다.

JSON 예시:
{
  "photo_1": [{"box_2d": [ymin, xmin, ymax, xmax], "label": "발화추정지점"}],
  "photo_2": [{"box_2d": [ymin, xmin, ymax, xmax], "label": "발화추정지점"}]
}

※ 본 AI 분석 결과는 현장 조사를 위한 보조 참고 자료이며, 법적 효력을 갖지 않습니다.
"""

            with st.spinner("Gemini AI가 연소확대 경로 및 발화추정지점을 정밀 분석 중입니다..."):
                content_payload = images + [prompt]
                
                # gemini-3.6-flash 모델로 변경 완료
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=content_payload
                )
                response_text = response.text

                bbox_data = parse_json_from_response(response_text)

                st.success("통합 분석 완료!")
                st.subheader("📌 발화추정지점 감식 결과 (시각화)")

                vis_cols = st.columns(min(len(images), 5))
                for idx, img in enumerate(images):
                    photo_key = f"photo_{idx+1}"
                    annotated_img = img.copy()

                    if bbox_data and photo_key in bbox_data and bbox_data[photo_key]:
                        boxes = bbox_data[photo_key]
                        annotated_img = draw_bounding_boxes(img, boxes)

                    with vis_cols[idx % 5]:
                        st.image(annotated_img, caption=f"사진 {idx+1} (발화지점 표기)", use_container_width=True)

                st.markdown("---")
                st.subheader("📋 상세 분석 보고서")
                
                clean_text = re.sub(r'```json\s*\{.*?\}\s*```', '', response_text, flags=re.DOTALL)
                clean_text = re.sub(r'\{"photo_1".*?\}', '', clean_text, flags=re.DOTALL)
                st.markdown(clean_text)

        except Exception as e:
            st.error(f"오류가 발생했습니다: {e}")

elif not api_key:
    st.info("좌측 사이드바에 Google Gemini API Key를 입력해주세요.")