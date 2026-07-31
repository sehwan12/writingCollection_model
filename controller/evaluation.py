from fastapi import APIRouter, Depends
from database import get_db
from dto.resultDTO import ResultCreate, ResultResponse
from service.missionRecordService import clear_mission_record, create_mission_record, update_submission_time
from service.resultService import create_result
from aiModel.utils.image_utils import merge_images
from aiModel.utils.image_utils import decode_base64_image_list
from aiModel.utils.font_score_utils import evaluate_character
from aiModel.utils.stroke_utils import count_jamo_matches, has_jongseung, extract_letters #1차 스테이지 보완
from sqlalchemy.orm import Session
from service.userService import get_user_by_id

router=APIRouter()

reader = None  # will be initialized lazily

@router.post("/evaluate", response_model=ResultResponse)
async def evaluate_handwriting(payload: ResultCreate,  db: Session = Depends(get_db)):
    global reader
    if reader is None:
        from aiModel import easyocr_mk2 as easyocr # 수정된 easyocr 모듈 임포트
        reader = easyocr.Reader(
            ['ko'],
            gpu=False,                     # GPU 대신 CPU만 사용
            #model_storage_directory='/home/ec2-user/.easyocr_cache',   # 모델 캐시 경로 변경(AWS EC2용)
            model_storage_directory='./.easyocr_cache',
            download_enabled=True,        # 불필요한 다운로드 방지
            verbose=False                  # 로깅 최소화
        )
    current_user=get_user_by_id(db=db, user_id=payload.user_id)
    if not current_user:
        return {"error": "User not found"}, 404

    #1)Mission Record 생성 
    mission_record=create_mission_record(db, payload)
    
    #2)모델 채점
    results = []  # 각 셀의 결과 저장용
    recognized_texts = ""  # 인식된 텍스트 저장용
    summary = ["", "", "", ""] # 각 단계별 틀린 글자 요약 저장용


    # 각 글자자에 대해 반복
    for cell_id in payload.cell_images.keys():
        # 0. 데이터 추출
        cell_images = payload.cell_images.get(cell_id)
        if not cell_images:
            continue  # 없으면 건너뜀


        stroke_counts = payload.detailed_strokecounts.get(cell_id)
        stroke_points = payload.firstandlast_stroke.get(cell_id)
        practice_syllabus = payload.practice_text[int(cell_id)]
        user_type = payload.user_type

        # 1. 이미지 디코딩
        images = decode_base64_image_list(cell_images)

        # 2. 병합
        img_bytes = merge_images(images)

        # 3. OCR
        ocr_results = reader.readtext(img_bytes, detail = 0, decoder = 'greedy')  # detail=0 으로 설정하여 (text, confidence) 튜플 대신 텍스트만 반환

        # 4. OCR 결과 확인
        passed_ocr = False

        # 4_a. 정확히 맞으면 통과
        recognized_text = ocr_results[0] if ocr_results else None  # 기본값 설정
        if recognized_text == practice_syllabus : # 정확히 맞는 경우
            recognized_texts = "완벽 => " + recognized_text  # 저장
            passed_ocr = True
            

        # 4_b. 틀렸지만 후보군내에서 자모음이 맞는 경우가 있을 시 통과
        else : 
            # 3. OCR_TOP K
            ocr_results = reader.readtext(img_bytes, detail = 0, decoder = 'greedy_best2')  # detail=0 으로 설정하여 (text, confidence) 튜플 대신 텍스트만 반환
            recognized_text = ocr_results[0] if ocr_results else ""  # 기본값 설정

            eval_count = 2 if has_jongseung(practice_syllabus) else 2 # 종성이 있으면 초중종[3], 없으면 초중[2]  인데 일단 2로 통일
            if eval_count <= count_jamo_matches(recognized_text, practice_syllabus) :
                recognized_texts = "괜찮음(후보군) => " + extract_letters(recognized_text)
                passed_ocr = True

        if not passed_ocr: recognized_texts = "인식실패 => " + recognized_text #1차 스테이지 실패 처리

        # 5. 평가 함수 호출
        score_result = evaluate_character(passed_ocr, images, stroke_counts, stroke_points, practice_syllabus, user_type)

        results.append({
            "original_text": practice_syllabus,
            "score": score_result["score"],
            "stage": score_result["stage"],
            "feedback" : score_result["reason"],
            "recognized_text": recognized_texts,
            "stage2_debug_state": score_result.get("stage2_debug_state", None),  # 2차 스테이지 디버그 정보가 있으면 포함
            "stage3_debug_state": score_result.get("stage3_debug_state", None),  # 3차 스테이지 디버그 정보가 있으면 포함
            "stage4_debug_state": score_result.get("stage4_debug_state", None)   # 4차 스테이지 디버그 정보가 있으면 포함
        })

        # 6. summary 업데이트 로직 
        stage_string = score_result["stage"]      # ex: "0110"
        current_char = practice_syllabus          # ex: "안"

        for i, result_code in enumerate(stage_string):
            if result_code == '1': # i번째 단계에서 실패했다면
                summary[i] += current_char # summary의 i번째 칸에 현재 글자를 추가

        

        # 실패 단계 기록
        # if score_result["stage"] != "완료":
        #     fail_stage_counter[score_result["stage"]] = fail_stage_counter.get(score_result["stage"], 0)


    # 평균 계산
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0

    # 최종 피드백들
    final_feedbacks = [r["feedback"] for r in results]

    # 3) Result 저장
    create_result(
        db, 
        mission_record.mission_id,
        avg_score,
    )

    # 제출 시간 업데이트
    update_submission_time(db, mission_record.mission_id)

    # 4) 기준점수 넘으면 clear 처리
    PASSING_SCORE = 60.0
    if avg_score >= PASSING_SCORE:
        clear_mission_record(db, mission_record.mission_id)  


    #5) Response 반환
    return ResultResponse(
        avg_score=avg_score,
        summary=summary,
        feedback=final_feedbacks,
        results=results
    )

    
