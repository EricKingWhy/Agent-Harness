"""create_chat_model 的 reasoning_effort 注入（RUNTIME 子批次）。

reasoning_effort 是会话级思考深度控制。**两套词汇必须分开**：

- harness 语义档位（`REASONING_EFFORT_DESCRIPTIONS` 的 key）：`minimal | standard | deep`
  ——产品词汇，Web 层 validator 与前端清单引用它；
- provider 线格式枚举（OpenAI 兼容推理接口的 `reasoning_effort` 字段）：
  `none | minimal | low | medium | high | xhigh | max`
  ——**只认这几个字面量，其他值一律 400**（实测 `invalid_parameter_error`，
  input `'deep'`）。

`create_chat_model` 于是必须把语义档位翻译成线格式枚举后再注入；原样透传
会让「标准 / 深度」两档在真实对话中**必然** BadRequestError → run 立刻失败、
零输出（2026-09-08 ~ 09-11 生产日志反复出现）。不支持的 Provider 是否忽略
该字段由 Provider 决定，但发出去的字面量必须合法。

覆盖契约：
  G1：reasoning_effort="deep" → 模型拿到线格式 "high"；
  G1b：reasoning_effort="standard" → 模型拿到线格式 "medium"；
  G2：不传 reasoning_effort → 模型的 reasoning_effort 为 None；
  G3：传 reasoning_effort=None → 同默认；
  G4：reasoning_effort="minimal" → 线格式同名 "minimal"；
  G5：Web 层档位清单与线格式翻译表**键集一致**（漂移守护）。
"""

from __future__ import annotations

from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import (
    REASONING_EFFORT_WIRE,
    WIRE_REASONING_EFFORTS,
    create_chat_model,
)


def _harness_levels() -> tuple[str, ...]:
    """Web 层 validator 认的档位（请求体取值的单一事实源）。

    函数内 import：model 测试车道不必在收集期拖起整个 FastAPI app。
    """
    from agent_harness.web.app import REASONING_EFFORT_DESCRIPTIONS

    return tuple(REASONING_EFFORT_DESCRIPTIONS)


def _config() -> ModelConfig:
    return ModelConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com",
        temperature=0.2,
    )


def test_create_chat_model_translates_deep_to_wire_enum():
    """G1：语义档位 "deep" → 线格式 "high"（不能原样发 "deep"）。"""
    model = create_chat_model(_config(), reasoning_effort="deep")
    assert getattr(model, "reasoning_effort", None) == "high"


def test_create_chat_model_translates_standard_to_wire_enum():
    """G1b：语义档位 "standard" → 线格式 "medium"（不能原样发 "standard"）。"""
    model = create_chat_model(_config(), reasoning_effort="standard")
    assert getattr(model, "reasoning_effort", None) == "medium"


def test_create_chat_model_no_reasoning_effort_by_default():
    """G2：不传 reasoning_effort → 模型的 reasoning_effort 为 None。"""
    model = create_chat_model(_config())
    assert getattr(model, "reasoning_effort", None) is None


def test_create_chat_model_none_reasoning_effort():
    """G3：传 reasoning_effort=None → 同默认。"""
    model = create_chat_model(_config(), reasoning_effort=None)
    assert getattr(model, "reasoning_effort", None) is None


def test_create_chat_model_minimal_reasoning_effort():
    """G4：语义档位 "minimal" 线格式同名。"""
    model = create_chat_model(_config(), reasoning_effort="minimal")
    assert getattr(model, "reasoning_effort", None) == "minimal"


def test_every_harness_level_maps_into_legal_wire_enum():
    """G4b（invariant）：**任何** harness 档位翻译后都必须落在 provider 合法枚举内。

    `deep` 这档曾经被原样发出去，导致真实会话每一次 run 都 400。这条断言把
    「不允许再出现非法字面量」变成结构性约束——档位集合直接取自 Web 层
    validator 的事实源（不在这里再抄一份名单），新增档位忘了翻译表就红。
    """
    for level in _harness_levels():
        model = create_chat_model(_config(), reasoning_effort=level)
        wire = getattr(model, "reasoning_effort", None)
        assert wire in WIRE_REASONING_EFFORTS, (
            f"harness 档位 {level!r} 翻译成了非法线格式字面量 {wire!r}——"
            f"provider 会返回 400。合法集合：{sorted(WIRE_REASONING_EFFORTS)}"
        )


def test_web_catalog_keys_and_wire_table_do_not_drift():
    """G5（drift guard）：Web validator 认的档位集合 == 翻译表键集。

    两者键集不一致 = 某个档位穿过 validator 却在 provider 层被丢弃（静默
    失效）。G4b 会以「非法字面量」的形式先红，G5 补一句更直白的诊断。
    """
    assert set(_harness_levels()) == set(REASONING_EFFORT_WIRE), (
        "Web 档位清单与线格式翻译表键集漂移："
        f"catalog={sorted(_harness_levels())} "
        f"wire={sorted(REASONING_EFFORT_WIRE)}"
    )
