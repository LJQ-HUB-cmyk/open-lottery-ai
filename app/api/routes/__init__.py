from .agent import router as agent_router
from .analysis import router as analysis_router
from .data import router as data_router
from .health import router as health_router
from .hit_analysis import router as hit_analysis_router
from .models import router as models_router
from .predict import router as predict_router
from .train import router as train_router

__all__ = [
    "health_router",
    "data_router",
    "train_router",
    "predict_router",
    "models_router",
    "analysis_router",
    "agent_router",
    "hit_analysis_router"
]