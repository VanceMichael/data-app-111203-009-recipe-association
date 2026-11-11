# 数据契约

材料试制记录以分号分隔的组分集合，按工厂计算批次数量和加权良率。

主测量 `yield_rate` 的单位为比例，主体字段是 `lot`，核算维度是 `plant`。`observation_id` 是文件内唯一观测编号，主体允许重复观测。数值只接受有限值；空单元格解析为 None，不能直接当成零。额外列不进入当前核算。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `observation_id` | str | 必填 |
| `lot` | str | 必填 |
| `plant` | str | 必填 |
| `month` | int | 允许空值，空值不是零 |
| `items` | str | 允许空值，空值不是零 |
| `yield_rate` | float | 必填 |
| `size` | int | 允许空值，空值不是零 |
| `recipe_version` | str | 允许空值，空值不是零 |

时间字段 day、week、tick、hour、minute、cycle、start_day、reported_day、known_at、visible_at、opened、observed 均以各字段名所述的相对时间单位表示整数；不同字段并不必然代表同一种时间。缺少的登记码与浓度等信息保持为空。示例只表达产品数据结构，不能代替实际调查资料。
