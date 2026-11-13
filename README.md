# recipe-association

材料试制记录以分号分隔的组分集合，按工厂计算批次数量和加权良率；`discovery` 命令把 lot 事务按月份截为发现期与验证期，形成复验候选线索。

## 使用

运行需要 Python 3.11 或更新版本，没有第三方运行依赖。数据在本地处理，不请求外部接口。

```bash
python3 -m analysis_app summary
python3 -m analysis_app summary --input data/observations.csv --output output/summary.json

python3 -m analysis_app discovery
python3 -m analysis_app discovery --min-support 5 --max-order 3 \
    --max-candidate-sets 500 --split-month 8 --fdr 0.05 \
    --output output/discovery.json
```

标准输出是完整 JSON，输出文件使用临时文件原子替换；失败退出码为 2，不覆盖既有结果。空数据集保留零计数与空分组，缺失数值不进入数值分母。数据指纹由按 observation_id 排序后的解析记录计算。

## discovery 的统计边界

- 一个 lot 是一个事务：同 lot 多观测合并、items 重复组分归一；支持度按批次计数，`size` 只在良率关联里作为加权权重。
- 发现期（`month < split-month`）只按最小支持批次与最大组合阶数筛规则；逐层枚举并受 `--max-order` 与 `--max-candidate-sets` 双重硬上限约束，不枚举无界幂集，每个被淘汰候选都记录原因。
- 规则集合在进入验证期前冻结，验证期不新增规则；验证期（`month >= split-month`）只在同厂批次内比较命中/未命中的加权良率，全部“规则 × 可检验工厂”检验组成一个 BH 检验族，一次性校正，不做事后分厂挑选。
- 仅一座工厂出现、或厂内缺少可比批次的规则只能作为共现发现；总体（跨厂合并）效应仅用于提示辛普森式冲突，显著性一律以厂内结果为准。
- 结论分为 `validated_association`、`not_validated`、`cooccurrence_only`、`eliminated_validation_empty`，并附验证效应、跨厂覆盖、方向稳定性与淘汰原因；结果是相关线索，不输出因果结论，也不建议直接更换配方。

## 验证与容器

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q analysis_app
python3 -I tools/generate_observations.py
docker build -t recipe-association .
docker run --rm recipe-association
docker run --rm recipe-association discovery --max-order 2
```

容器内也可执行 `python -m unittest discover -s tests -v`。镜像构建阶段取得 Python 镜像，产品启动、测试和演示均无需下载。小规模样例的完整单元测试和 summary/discovery 可以连续执行，不需要等待定时任务。

## 代码与数据

- `analysis_app/io.py`：有类型的 CSV 读取、完整性校验及内容指纹。
- `analysis_app/schema.py`：字段类型、主体与聚合维度。
- `analysis_app/domain.py`：当前业务核算函数。
- `analysis_app/summary.py`：确定性的分组与数值口径。
- `analysis_app/transactions.py`：lot 事务归一化与发现/验证月份切分。
- `analysis_app/mining.py`：有界逐层频繁项集挖掘与淘汰留痕。
- `analysis_app/statistics.py`：厂内加权良率对比、正态近似检验与 BH 校正。
- `analysis_app/discovery.py`：规则冻结、验证期复验、跨厂覆盖与结论分级。
- `analysis_app/cli.py`：本地命令及原子输出。
- `tools/generate_observations.py`：固定种子的本地合成数据生成器。
- `docs/data.md`：数据契约、权重口径与合成试验段设计。

演示数据全部为本地合成，不对应现实机构、设备或人员；不能用来推断真实业务效果。
