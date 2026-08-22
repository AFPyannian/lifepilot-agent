from pathlib import Path
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.config import Settings
from app.exceptions import ConfigurationError


def create_embedding_model(settings: Settings) -> HuggingFaceEmbeddings:
    """
        创建本地Embedding模型。

        Embedding模型负责把文本转换成数字向量，不负责生成最终回答。
    """
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
            # 如果已正确安装CUDA版本PyTorch，可以在.env中改成cuda。
            "device": settings.embedding_device,

            # 强制只读取本地文件。即使模型文件不完整，也不会再次联网下载。
            "local_files_only": True,
        },
        encode_kwargs={
            # 对向量进行归一化，方便使用余弦相似度进行检索。
            "normalize_embeddings": True,
        },
    )


def create_knowledge_vector_store(settings: Settings) -> Chroma:
    """
        创建持久化Chroma向量数据库。

        persist_directory存在时，程序重启后仍能读取原来的向量。
    """
    settings.chroma_persist_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return Chroma(
        collection_name="lifepilot_knowledge",
        embedding_function=create_embedding_model(settings),
        persist_directory=str(settings.chroma_persist_directory),
    )