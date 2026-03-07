import os
import uuid
import httpx
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from core.security import get_current_user
from models import User, KakaoPayPayment, TokenTransaction
from schemas import PaymentReadyRequest, PaymentReadyResponse
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/payment", tags=["Payment"])

KAKAO_PAY_READY_URL = "https://open-api.kakaopay.com/online/v1/payment/ready"
KAKAO_PAY_APPROVE_URL = "https://open-api.kakaopay.com/online/v1/payment/approve"
KAKAO_SECRET_KEY = os.getenv("KAKAO_PAY_SECRET_KEY")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

CID = "TC0ONETIME"    # 카카오페이 테스트 가맹점 코드
TOKEN_PRICE = 100     # 토큰 1개 = 100원


def _kakao_headers():
    return {
        "Authorization": f"SECRET_KEY {KAKAO_SECRET_KEY}",
        "Content-Type": "application/json"
    }


# ─── 결제 준비 ────────────────────────────────────────────────────────────────

@router.post("/ready", response_model=PaymentReadyResponse, status_code=200)
async def payment_ready(
    request: PaymentReadyRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    카카오페이 결제 준비.
    프론트는 응답의 next_redirect_pc_url(또는 mobile_url)로 사용자를 리다이렉트.
    """
    user = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

    partner_order_id = str(uuid.uuid4())
    total_amount = request.quantity * TOKEN_PRICE

    # DB에 READY 상태로 먼저 저장 (tid는 카카오 응답 후 업데이트)
    payment = KakaoPayPayment(
        user_id=user.id,
        cid=CID,
        partner_order_id=partner_order_id,
        partner_user_id=user.user_id,
        item_name=request.item_name,
        quantity=request.quantity,
        total_amount=total_amount,
        tax_free_amount=0,
        status="READY"
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # 카카오페이 Ready API 호출
    body = {
        "cid": CID,
        "partner_order_id": partner_order_id,
        "partner_user_id": user.user_id,
        "item_name": request.item_name,
        "quantity": request.quantity,
        "total_amount": total_amount,
        "tax_free_amount": 0,
        "approval_url": f"{FRONTEND_URL}/payment/success?partner_order_id={partner_order_id}",
        "cancel_url":   f"{FRONTEND_URL}/payment/cancel",
        "fail_url":     f"{FRONTEND_URL}/payment/fail"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(KAKAO_PAY_READY_URL, headers=_kakao_headers(), json=body)

    if resp.status_code != 200:
        db.delete(payment)
        db.commit()
        raise HTTPException(status_code=502, detail=f"카카오페이 오류: {resp.text}")

    kakao = resp.json()

    # 카카오 응답 데이터 저장
    payment.tid = kakao["tid"]
    payment.next_redirect_pc_url = kakao.get("next_redirect_pc_url", "")
    payment.next_redirect_mobile_url = kakao.get("next_redirect_mobile_url", "")
    db.commit()

    return PaymentReadyResponse(
        tid=kakao["tid"],
        next_redirect_pc_url=kakao["next_redirect_pc_url"],
        partner_order_id=partner_order_id
    )


# ─── 결제 승인 (카카오 → 서버 콜백) ──────────────────────────────────────────

@router.get("/approve")
async def payment_approve(
    pg_token: str = Query(...),
    partner_order_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    카카오페이 결제 완료 후 리다이렉트되는 콜백.
    pg_token과 partner_order_id를 받아 최종 승인 처리.
    """
    payment = db.query(KakaoPayPayment).filter(
        KakaoPayPayment.partner_order_id == partner_order_id,
        KakaoPayPayment.status == "READY"
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="결제 정보를 찾을 수 없거나 이미 처리된 결제입니다.")

    # 카카오페이 승인 API 호출
    body = {
        "cid": payment.cid,
        "tid": payment.tid,
        "partner_order_id": partner_order_id,
        "partner_user_id": payment.partner_user_id,
        "pg_token": pg_token
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(KAKAO_PAY_APPROVE_URL, headers=_kakao_headers(), json=body)

    if resp.status_code != 200:
        payment.status = "FAILED"
        db.commit()
        raise HTTPException(status_code=502, detail=f"결제 승인 실패: {resp.text}")

    # 결제 승인 DB 업데이트
    payment.pg_token = pg_token
    payment.approved_at = datetime.datetime.utcnow()
    payment.status = "APPROVED"

    # 유저 토큰 잔액 증가
    user = db.query(User).filter(User.id == payment.user_id).first()
    user.token_balance += payment.quantity

    # 토큰 충전 내역 기록
    transaction = TokenTransaction(
        user_id=user.id,
        amount=payment.quantity,
        transaction_type="CHARGE",
        payment_id=payment.id,
        description=f"카카오페이 충전 ({payment.item_name} {payment.quantity}개)"
    )
    db.add(transaction)
    db.commit()

    return {
        "message": "결제 승인 완료",
        "charged_tokens": payment.quantity,
        "current_balance": user.token_balance,
        "payment_date": payment.approved_at
    }


# ─── 결제 취소 / 실패 콜백 ────────────────────────────────────────────────────

@router.get("/cancel")
async def payment_cancel(
    partner_order_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """사용자가 결제창에서 취소한 경우."""
    payment = db.query(KakaoPayPayment).filter(
        KakaoPayPayment.partner_order_id == partner_order_id
    ).first()
    if payment and payment.status == "READY":
        payment.status = "CANCELED"
        db.commit()
    return {"message": "결제가 취소되었습니다."}


@router.get("/fail")
async def payment_fail(
    partner_order_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """결제 실패 시 카카오가 리다이렉트하는 콜백."""
    payment = db.query(KakaoPayPayment).filter(
        KakaoPayPayment.partner_order_id == partner_order_id
    ).first()
    if payment and payment.status == "READY":
        payment.status = "FAILED"
        db.commit()
    return {"message": "결제에 실패했습니다."}


# ─── 토큰 잔액 / 내역 조회 ────────────────────────────────────────────────────

@router.get("/balance")
async def get_token_balance(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """현재 토큰 잔액 조회."""
    user = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
    return {"token_balance": user.token_balance}


@router.get("/history")
async def get_token_history(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """토큰 충전/사용 전체 내역 조회 (최신순)."""
    user = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

    transactions = (
        db.query(TokenTransaction)
        .filter(TokenTransaction.user_id == user.id)
        .order_by(TokenTransaction.created_at.desc())
        .all()
    )

    data = [
        {
            "id": t.id,
            "amount": t.amount,
            "transaction_type": t.transaction_type,
            "description": t.description,
            "created_at": t.created_at
        }
        for t in transactions
    ]

    return {"total_count": len(data), "data": data}
