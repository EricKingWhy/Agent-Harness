"""ModelConfig：把 Settings 解析成创建 ChatModel 所需的完整配置。

Provider 预设表是唯一允许出现厂商细节的地方。
未知 provider 在这里就抛错，而不是等到网络请求失败才发现。
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from agent_harness.config import Settings


class ConfigError(Exception):
    """配置错误（未知 provider、缺少必填项等）。"""


# 各厂商 OpenAI 兼容端点与默认模型。
#
# Phase 2（SDD 03 §16 ModelOption）：preset 可携带能力位元数据——
# display_name / context_window / speed_tier / supports_tools / supports_vision /
# supports_reasoning_summary。仅写入**已验证**的字段；不确定的省略
# （契约：「Unknown capabilities should be omitted, not guessed」）。
# 能力位字段全 Optional，旧消费者只读 model_base_url / model_name，无破坏。
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "model_base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
        # OpenAI 兼容 tool_calls 已在生产路径验证（项目主链就是工具驱动）。
        "supports_tools": True,
        # deepseek-chat 窗口 64K（官方公告）；reasoning 是 deepseek-reasoner 才有，
        # 默认 preset 不带 reasoning_summary 能力位（诚实标注）。
        "context_window": 64000,
        "speed_tier": "fast",
    },
    "qwen": {
        "model_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-plus",
        # DashScope 兼容模式支持 function calling。
        "supports_tools": True,
    },
    # 腾讯 Coding Plan（OpenAI 兼容）。base_url 不含 /chat/completions，
    # SDK 会自动拼接；无默认模型，MODEL_NAME 必填。
    "tencent": {
        "model_base_url": "https://chatapi.weixin.qq.com/openai/v1",
        "model_name": "",
    },
    # SenseAudio（OpenAI 兼容）。无默认模型，MODEL_NAME 必填。
    "senseaudio": {
        "model_base_url": "https://api.senseaudio.cn/v1",
        "model_name": "",
    },
    # 智谱 BigModel（OpenAI 兼容）。无默认模型，MODEL_NAME 必填
    # （如 glm-4.5-air；思考模型，流式 reasoning 增量连续，不触发 idle 看门狗）。
    "zhipu": {
        "model_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "",
        # GLM-4 系列支持 function calling。
        "supports_tools": True,
    },
}

#: 能力位字段清单（preset 与 catalog 共用）。值类型固定，便于解析校验。
_CAPABILITY_FIELDS: dict[str, type] = {
    "display_name": str,
    "context_window": int,
    "speed_tier": str,  # "fast" | "balanced" | "quality"
    "supports_tools": bool,
    "supports_vision": bool,
    "supports_reasoning_summary": bool,
}


def _pick_capabilities(source: dict[str, Any]) -> dict[str, Any]:
    """从 source dict 抽取已知能力位（仅声明的键）。省略 = 不猜测。"""
    return {k: source[k] for k in _CAPABILITY_FIELDS if k in source}


@dataclass(frozen=True)
class ModelCatalogEntry:
    """AGENT_MODELS 的一个可选模型（ADR-0016 §5，D-B②）。

    api_key 缺省回落 MODEL_API_KEY；base_url 缺省回落 provider 预设；
    temperature 缺省回落全局 TEMPERATURE。SecretStr 待遇与 Settings 层一致。

    Phase 2 加法：能力位字段全 Optional，catalog 可声明覆盖 preset（SDD 03 §16）。
    未声明（None）的字段在 list_models 渲染时回落到 provider preset。
    """

    name: str
    provider: str
    model_name: str
    base_url: str | None = None
    api_key: SecretStr | None = None
    temperature: float | None = None
    # 能力位（Phase 2 加法）——None = 未在 catalog 条目声明（回落 preset）。
    display_name: str | None = None
    context_window: int | None = None
    speed_tier: str | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    supports_reasoning_summary: bool | None = None

    def declared_capabilities(self) -> dict[str, Any]:
        """返回本条目【显式声明】的能力位（None 的不计入）。"""
        caps: dict[str, Any] = {}
        if self.display_name is not None:
            caps["display_name"] = self.display_name
        if self.context_window is not None:
            caps["context_window"] = self.context_window
        if self.speed_tier is not None:
            caps["speed_tier"] = self.speed_tier
        if self.supports_tools is not None:
            caps["supports_tools"] = self.supports_tools
        if self.supports_vision is not None:
            caps["supports_vision"] = self.supports_vision
        if self.supports_reasoning_summary is not None:
            caps["supports_reasoning_summary"] = self.supports_reasoning_summary
        return caps


def parse_model_catalog(settings: Settings) -> list[ModelCatalogEntry]:
    """解析 AGENT_MODELS（JSON 数组）；空 = 无可选模型（默认链照旧）。

    配置错误在此响亮失败（未知 provider / 重名 / 非法形状），绝不静默降级
    ——错误的 catalog 会让"会话级选模型"变成"永远落到默认链"的隐性 bug。
    """
    raw = (settings.agent_models.get_secret_value()
           if isinstance(settings.agent_models, SecretStr) else settings.agent_models)
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigError(f"AGENT_MODELS 不是合法 JSON: {error}") from error
    if not isinstance(parsed, list):
        raise ConfigError("AGENT_MODELS 必须是 JSON 数组")
    entries: list[ModelCatalogEntry] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            raise ConfigError("AGENT_MODELS 每个条目必须是对象")
        name = item.get("name")
        provider = item.get("provider")
        model_name = item.get("model_name", "")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("AGENT_MODELS 条目缺少非空 name")
        if name in seen:
            raise ConfigError(f"AGENT_MODELS 条目重名: {name!r}")
        seen.add(name)
        if not isinstance(provider, str) or provider not in PROVIDER_PRESETS:
            raise ConfigError(
                f"AGENT_MODELS 条目 {name!r} 的 provider 未知: {provider!r}，"
                f"可选: {sorted(PROVIDER_PRESETS)}"
            )
        if not isinstance(model_name, str) or not model_name:
            model_name = PROVIDER_PRESETS[provider]["model_name"]
        if not model_name:
            raise ConfigError(
                f"AGENT_MODELS 条目 {name!r} 缺少 model_name"
                f"（provider {provider!r} 无预设默认）"
            )
        api_key = item.get("api_key")
        temperature = item.get("temperature")
        if temperature is not None and not isinstance(temperature, (int, float)):
            raise ConfigError(f"AGENT_MODELS 条目 {name!r} 的 temperature 必须是数字")
        # 能力位（Phase 2 加法）：按 _CAPABILITY_FIELDS 类型校验，缺省 None。
        capability_kwargs: dict[str, Any] = {}
        for cap_field, cap_type in _CAPABILITY_FIELDS.items():
            if cap_field in item:
                value = item[cap_field]
                # bool 是 int 的子类，单独先判避免误收 int 当 bool。
                if cap_type is bool:
                    if not isinstance(value, bool):
                        raise ConfigError(
                            f"AGENT_MODELS 条目 {name!r} 的 {cap_field} 必须是 bool"
                        )
                elif cap_type is int:
                    if not isinstance(value, int) or isinstance(value, bool):
                        raise ConfigError(
                            f"AGENT_MODELS 条目 {name!r} 的 {cap_field} 必须是 int"
                        )
                else:
                    if not isinstance(value, str):
                        raise ConfigError(
                            f"AGENT_MODELS 条目 {name!r} 的 {cap_field} 必须是 string"
                        )
                capability_kwargs[cap_field] = value
        entries.append(ModelCatalogEntry(
            name=name, provider=provider, model_name=model_name,
            base_url=item.get("base_url") or None,
            api_key=SecretStr(api_key) if isinstance(api_key, str) and api_key else None,
            temperature=temperature,
            **capability_kwargs,
        ))
    return entries


def find_catalog_entry(
    settings: Settings, provider: str, model_id: str
) -> ModelCatalogEntry | None:
    """按 (provider, model_id) 查 catalog 条目（T7 #137 模型切换寻址）。

    model_id 命中条目 ``name``（前端/amend 用的 catalog 名）或上游 ``model_name``；
    provider 必须与条目一致——防止跨 provider 误选同名模型。``name`` 精确匹配优先
    于 ``model_name`` 匹配（否则条目 A 的 name 撞上条目 B 的 model_name 时结果由
    声明顺序决定）。未命中返回 None，由调用方翻译为领域异常 / CLI 提示。
    """
    entries = parse_model_catalog(settings)
    for entry in entries:
        if entry.provider == provider and entry.name == model_id:
            return entry
    for entry in entries:
        if entry.provider == provider and entry.model_name == model_id:
            return entry
    return None


class ModelConfig:
    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str,
        temperature: float,
        fallback: "ModelConfig | None" = None,
    ):
        # 运行期 SDK 要明文，但持有形态是 SecretStr：repr(config) / vars(config)
        # / pytest 失败局部变量等调试路径脱敏为 **********（与 Settings 层一致）。
        # get_secret_value() 是取明文的唯一出口。
        if not api_key.strip():
            raise ConfigError("ModelConfig 缺少 API key：空白 key 只会把失败推到首次 ainvoke")
        self.provider = provider
        self.model_name = model_name
        self.api_key = SecretStr(api_key)
        self.base_url = base_url
        self.temperature = temperature
        # Model Fallback 两级链（ADR-0014 决策 14）：瞬时故障切 fallback、
        # never 切回。V1 只消费第一级（Runtime 的 coordinator 持有两级结构）。
        self.fallback = fallback

    def get_secret_value(self) -> str:
        """取明文 key（仅 SDK 请求边界使用）。"""
        return self.api_key.get_secret_value()

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelConfig":
        config = cls._single_from(
            provider=settings.model_provider,
            model_name=settings.model_name,
            api_key=settings.model_api_key.get_secret_value(),
            base_url=settings.model_base_url,
            temperature=settings.temperature,
            key_env="MODEL_API_KEY",
        )
        config.fallback = cls._fallback_from(settings)
        return config

    @classmethod
    def _fallback_from(cls, settings: Settings) -> "ModelConfig | None":
        """settings 的 fallback 模型（ADR-0014 决策 14）；未配置 = None。

        from_settings 与 from_catalog 共享：会话级选择只替换 primary，
        fallback 链永不被 catalog 选择静默丢弃。
        """
        # FALLBACK_MODEL_PROVIDER 为空 = 单级（无 fallback），静默缺省。
        if not settings.fallback_model_provider:
            return None
        return cls._single_from(
            provider=settings.fallback_model_provider,
            model_name=settings.fallback_model_name,
            api_key=settings.fallback_model_api_key.get_secret_value(),
            base_url=settings.fallback_model_base_url,
            temperature=settings.temperature,
            key_env="FALLBACK_MODEL_API_KEY",
        )

    @classmethod
    def from_catalog(cls, settings: Settings, name: str) -> "ModelConfig":
        """按 catalog 名解析会话级模型（ADR-0016 §5，D-B②）。

        未知名字响亮失败（web 层映射 422）。fallback 链语义不动（ADR-0014）：
        catalog 项只替换 primary，fallback 仍由 FALLBACK_MODEL_* 决定。
        """
        entries = parse_model_catalog(settings)
        entry = next((e for e in entries if e.name == name), None)
        if entry is None:
            raise ConfigError(
                f"未知模型: {name!r}，可选: "
                f"{[e.name for e in entries] + ['（不传 model 参数 = 默认链）']}"
            )
        api_key = (entry.api_key.get_secret_value() if entry.api_key is not None
                   else settings.model_api_key.get_secret_value())
        resolved = cls(
            provider=entry.provider,
            model_name=entry.model_name,
            api_key=api_key,
            base_url=(entry.base_url
                      or PROVIDER_PRESETS[entry.provider]["model_base_url"]),
            temperature=(entry.temperature if entry.temperature is not None
                         else settings.temperature),
        )
        # fallback 链语义不动（ADR-0014）：catalog 选择只替换 primary。
        resolved.fallback = cls._fallback_from(settings)
        return resolved

    @classmethod
    def _single_from(
        cls, *, provider: str, model_name: str, api_key: str,
        base_url: str, temperature: float, key_env: str,
    ) -> "ModelConfig":
        """解析单个（primary 或 fallback）模型配置；未知 provider 在配置期就抛错。"""
        if provider not in PROVIDER_PRESETS:
            raise ConfigError(
                f"未知 provider: {provider!r}，可选: {sorted(PROVIDER_PRESETS)}"
            )

        preset = PROVIDER_PRESETS[provider]
        name = model_name or preset["model_name"]
        if not name:
            raise ConfigError(
                f"provider {provider!r} 无默认模型，必须在 .env 中配置 MODEL_NAME"
            )
        # 空 key 快速失败：已知 provider + 空 key 是确定性配置错误——不应静默
        # 构造后把失败推到首次 ainvoke 时由 SDK 抛模糊的 AuthenticationError；
        # 与未知 provider / 缺 model_name 一致在此快速失败（构造器还有一道
        # 通用校验兜底，这里给出的是更可操作的 .env 指引）。
        if not api_key:
            raise ConfigError(
                f"provider {provider!r} 缺少 API key，必须在 .env 中配置 {key_env}"
            )
        return cls(
            provider=provider,
            # 显式配置优先，否则用厂商预设
            model_name=name,
            base_url=base_url or preset["model_base_url"],
            api_key=api_key,
            temperature=temperature,
        )
