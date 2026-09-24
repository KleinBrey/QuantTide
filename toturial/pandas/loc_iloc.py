import pandas as pd

# 创建示例 DataFrame
df = pd.DataFrame(
    {
        "姓名": ["张三", "李四", "王五", "赵六", "钱七"],
        "年龄": [25, 30, 28, 35, 22],
        "城市": ["北京", "上海", "广州", "深圳", "杭州"],
    },
    index=[1, 3, 5, 7, 9],
)  # 注意：索引不是连续的

print("DataFrame：")
print(df)
print()

# loc: 使用标签索引（包含结束位置）
print("df.loc[1:5]（标签切片，包含5）：")
print(df.loc[1:5, ["姓名", "年龄"]])  # 选择行标签1到5，列标签为"姓名"和"年龄"
print()

# iloc: 使用位置索引（不包含结束位置）
print("df.iloc[0:2]（位置切片，不包含2）：")
print(df.iloc[0:2])
