"""创建本地中文向量模型和 Chroma 存储。"""


from pathlib import Path
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.config import Settings
from app.exceptions import ConfigurationError


def create_embedding_model(settings: Settings) -> HuggingFaceEmbeddings:
    """创建只读取本地文件的中文 Embedding 模型。"""
    model_path = Path(
        settings.embedding_model_name
    )

    if not model_path.exists():
        raise ConfigurationError(
            (
                "Local embedding model directory does not exist: {model_path}"
            ),
            (
                "未找到本地Embedding模型。 请先下载Embedding模型， 并检查模型目录：{model_path}"
            ),
        )

    if not model_path.is_dir():
        raise ConfigurationError(
            (
                "Local embedding model path is not a directory: {model_path}"
            ),
            (
                "Embedding模型路径不是目录，请检查：{model_path}"
            ),
        )

    return HuggingFaceEmbeddings(
        model_name=str(model_path),
        model_kwargs={

            "device": settings.embedding_device,


            "local_files_only": True,
        },
        encode_kwargs={

            "normalize_embeddings": True,
        },
    )


def create_knowledge_vector_store(settings: Settings) -> Chroma:
    """创建持久化 Chroma 向量存储。"""
    settings.chroma_persist_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return Chroma(
        collection_name="lifepilot_knowledge",
        embedding_function=create_embedding_model(settings),
        persist_directory=str(settings.chroma_persist_directory),
    )