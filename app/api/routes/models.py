# -*- coding: utf-8 -*-
"""
模型管理接口：列出已训练模型、下载模型文件。
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import glob
from app.core.config import settings

router = APIRouter(prefix="/models", tags=["Models"])

@router.get("/list")
async def list_models():
    """列出所有已保存的模型文件（.pt）"""
    save_dir = settings.MODEL_SAVE_DIR
    if not os.path.exists(save_dir):
        return {"models": []}
    # 查找所有 .pt 和 .joblib 文件
    pt_files = glob.glob(os.path.join(save_dir, "*.pt"))
    scaler_files = glob.glob(os.path.join(save_dir, "*_scaler.joblib"))
    files = [os.path.basename(f) for f in pt_files + scaler_files]
    return {"models": sorted(files)}

@router.get("/download/{model_name}")
async def download_model(model_name: str):
    """下载指定的模型文件"""
    # 防止路径遍历攻击
    if ".." in model_name or "/" in model_name or "\\" in model_name:
        raise HTTPException(400, "Invalid file name")
    model_path = os.path.join(settings.MODEL_SAVE_DIR, model_name)
    if not os.path.exists(model_path):
        raise HTTPException(404, "Model not found")
    return FileResponse(model_path, filename=model_name)