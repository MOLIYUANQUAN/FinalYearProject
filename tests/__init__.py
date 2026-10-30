"""测试统一用演示数据和一个临时状态目录：不碰真日历、真邮箱、本机记忆，也不需要 API Key。"""

import os
import tempfile

STATE_DIR = tempfile.mkdtemp(prefix="friday-test-state-")

# 必须在 import src.* 之前设好：config 在 import 时读路径
os.environ["FRIDAY_STATE_DIR"] = STATE_DIR
os.environ["CALENDAR_BACKEND"] = "mock"
os.environ["MAIL_BACKEND"] = "mock"
os.environ["TASKS_BACKEND"] = "mock"
os.environ["FRIDAY_ACCESS_TOKEN"] = ""
os.environ["FRIDAY_URL"] = ""
# 不受本机 .env 里选的型号影响：默认就是 GPT-5（Claude 那条路用假客户端单独测）
os.environ["OPENAI_MODEL"] = "gpt-5"
os.environ["FRIDAY_MODEL"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["FRIDAY_REASONING"] = "low"
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")
# 测试不去真的 GitHub（要测的地方自己 mock）
os.environ["FRIDAY_GITHUB_OFFLINE"] = "1"
# 也不去请模型给日历标题起名（要测的地方自己 mock）
os.environ["FRIDAY_NAMING"] = "off"

from agents import set_tracing_disabled  # noqa: E402

set_tracing_disabled(True)
