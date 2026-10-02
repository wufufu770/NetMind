# SBOM 生成方式选型记录

> 这份记录存在的原因：`cyclonedx-py` 有两个子命令都能生成 SBOM，都返回 0，
> 但**产物天差地别**。选错了不会报错，只会产出一份内容错的 SBOM。

## 两种写法

| 写法 | 数据来源 | 是否需要先装依赖 |
|---|---|---|
| `cyclonedx-py environment` | 扫**当前已安装的包** | 需要 |
| `cyclonedx-py requirements` | 读**声明文件**（requirements.txt） | 不需要 |

## 为什么 supply-chain job 不能用 environment

该 job 只装了两个工具，**没有把项目依赖装进环境**：

```yaml
- name: pip-audit
  run: |
    pip install pip-audit==2.10.1
    pip-audit -r backend/requirements.txt      # ← 这是「读文件比对」，不是「装进环境」
- name: SBOM
  run: |
    pip install cyclonedx-bom
    cyclonedx-py requirements --output-file netmind-sbom.json
    working-directory: backend
```

`pip-audit -r` 只是把文件交给漏洞数据库比对，**不会安装任何东西**。

## 实测（模拟 CI 的干净环境：只装 pip-audit + cyclonedx-bom）

```
写法 A：cyclonedx-py environment
  退出码 0
  组件数 50 —— CacheControl / Pygments / arrow / attrs / boolean.py / certifi …
  NetMind 依赖命中：0 个

写法 B：cyclonedx-py requirements
  退出码 0
  组件数 12 —— PyYAML, click, fastapi, httpx, langgraph, pydantic,
                 pytest, pytest-asyncio, python-dotenv, rich, typer, uvicorn
  与 backend/requirements.txt 完全一致
```

## 结论

**写法 A 绿但空。** 退出码 0、artifact 正常上传、CI 变绿——而里面没有 NetMind 的
任何一个依赖。采购拿到这份 SBOM 会以为供应链已登记完整。

**绿的假数据比红的真失败更危险**：红的会被人看见并去修，绿的会被人采信。

因此采用写法 B：`requirements` 子命令 + `working-directory: backend`。
它从声明文件生成，不需要安装、不会随环境漂移、也不依赖 job 的安装顺序。

## 防回归

门禁 `sbom-covers-declared-deps` 会把 ci.yml 里写的命令真跑一遍，校验产物是
合法 CycloneDX 且包含 requirements.txt 里**每一个**声明依赖。
