from typing import Annotated, Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from backend.scripts.registry import SCRIPTS


class CronSchedule(BaseModel):
    model_config = ConfigDict(extra='forbid')

    trigger: Literal['cron']
    cron: str

    @field_validator('cron')
    @classmethod
    def validate_cron(cls, value: str) -> str:
        # Cron 语法交给 APScheduler 校验，不自己编写解析器。
        CronTrigger.from_crontab(value)
        return value


class IntervalSchedule(BaseModel):
    model_config = ConfigDict(extra='forbid')

    trigger: Literal['interval']
    seconds: int = Field(strict=True, gt=0)


class TaskInput(BaseModel):
    """创建和编辑共用的表单；校验通过后交给 Service 普通字典。"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1, max_length=100)
    script_id: str
    params: dict = Field(default_factory=dict)
    # None 表示仅手动运行；按 trigger 选择对应的配置格式。
    schedule: Annotated[CronSchedule | IntervalSchedule, Field(discriminator='trigger')] | None = None
    enabled: StrictBool = True

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError('任务名称不能为空')
        return value.strip()

    @model_validator(mode='after')
    def validate_script_params(self):
        script = SCRIPTS.get(self.script_id)
        if script is None:
            raise ValueError('请选择已注册的脚本')
        defaults = script.get('params', {})
        if self.params.keys() - defaults.keys():
            raise ValueError('脚本包含不支持的参数')
        # 未填写的参数使用注册表中的默认值。
        self.params = {**defaults, **self.params}
        if 'lookback_days' in self.params:
            days = self.params['lookback_days']
            # bool 也是 Python 整数，使用 type 排除 true/false。
            if type(days) is not int or days < 1:
                raise ValueError('同步天数必须是正整数')
        return self


class TaskEnabled(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool
