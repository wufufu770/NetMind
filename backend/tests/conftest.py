"""测试环境的统一前提。

两件事必须在这里固定住，否则「测试能过」这件事本身就不可信。

## 1. 业务逻辑测试跑在「本机访问」姿态下

新增的默认安全策略是「没配 token 就只许本机」。而 starlette 的 TestClient 默认
对端是 `('testclient', 50000)`，不是 loopback——于是所有业务逻辑测试都会被 403，
测的东西跟认证毫无关系。

取舍：业务测试视作 127.0.0.1 且不配 token；认证行为本身由
`test_access_and_observability.py` 单独覆盖（它显式指定 client host、显式设 token）。

## 2. 每个会话用独立的数据文件

这条是**实测踩出来的**：先跑到一半时 `test_dangerous_commands_blocked_unless_registered_rollback`
突然失败，单跑也失败。查下来是 `data/netmind_store.json`（已 gitignore）跨运行累积——
上一个测试运行把 `cookie=0x4e65744d5afe0001` 登记进了 STORE 并落盘，这次运行
STORE 启动时读到它，于是「未登记的 cookie」断言变成了「已登记」。

也就是说：**这套测试在干净机器上绿、在跑过一次���机器上红**。那不是环境问题，
是测试依赖了外部可变状态。商业项目不能有这种测试——它会让你在「明明没改代码」
的时候追一个不存在的回归。

处理：在导入 app 之前把 NETMIND_DATA_FILE 指到临时目录，每个会话独立。
"""
import os
import tempfile

# 必须在任何 app.* 导入之前设好——store 在模块导入期就会读这个变量
_TMP = tempfile.mkdtemp(prefix='netmind-test-data-')
os.environ['NETMIND_DATA_FILE'] = os.path.join(_TMP, 'store.json')

import pytest  # noqa: E402

from app.core import access as _access  # noqa: E402


@pytest.fixture(autouse=True)
def _treat_testclient_as_local(monkeypatch):
    """把测试请求视作本机访问，使业务测试不受认证门影响。"""
    monkeypatch.setattr(_access, '_client_host', lambda request: '127.0.0.1')
    for k in ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_TRUST_PROXY'):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _reset_shared_store():
    """每个用例前清空 STORE 的可变状态。

    STORE 是模块级单例，测试文件之间共享。其中 `flow_cookies` 尤其敏感：
    一个用例登记了 cookie，另一个用例测「未登记的 cookie 应被拒绝」就会假失败。
    这与「跨运行累积」是同一类问题，只是这次发生在同一进程内的用例之间。
    """
    from app.store import STORE
    # 故障注入类测试会全局替换 os.replace / builtins.open；后台自动保存线程
    # 若同时在跑就会撞上，产生时序相关的假失败（实测同代码连跑两次结果不同）。
    STORE._autosave_enabled = False
    STORE.flow_cookies.clear()
    STORE.executions.clear()
    STORE.approvals.clear()
    STORE.telemetry.clear()
    STORE.logs.clear()
    STORE.flow_cookies.clear()
    yield
