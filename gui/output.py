"""把完整诊断日志转换为面向用户的简短输出，不修改磁盘记录。"""
import re


def display_message(message, tag="black"):
    if isinstance(message, list):
        return message, tag
    text = str(message).strip()
    if not text:
        return None
    if text.startswith(("[耗时]", "[选中校验]", "[等待]", "[翻页校验]", "[整页滑动]",
                        "[测试]", "[激活诊断]", "[日志]", "[校验]", "[开始]", "[结束摘要]")):
        return None
    if text.startswith("[整页]"):
        if "扫描结束" in text:
            return "扫描完成。", "blue"
        if "停止" in text:
            return text.replace("[整页] ", ""), tag
        return None
    if text.startswith("[系统]") and any(word in text for word in ("分辨率", "缩放系数", "探测行", "全局尾扫")):
        return None
    if text.startswith("[异常]"):
        return text.splitlines()[0].replace("[异常]", "操作中断：", 1) + "（详细原因已保存到日志）", "red"
    if text.startswith("[错误]"):
        text = text.splitlines()[0]
        text = re.sub(r"[:：]\s*\{.*", "，详情已保存到日志", text)
        return text.replace("[错误] ", ""), "red"
    match = re.fullmatch(r"-+ 检查: (\d+-\d+) -+", text)
    if match:
        return f"--------------------{match.group(1)}--------------------", "black"
    if text.startswith("[预览] 规则匹配："):
        return "预览匹配：" + text.split("：", 1)[1].split("；", 1)[0], "blue"
    if text == "判定为无用基质，准备废弃":
        return None
    for source, replacement in (
            ("-> 已执行锁定指令", "已锁定"), ("-> 已执行废弃指令", "已标记废弃"),
            ("-> 该基质已锁定，跳过", "已锁定 · 保持不变"),
            ("-> 该基质已废弃，跳过", "已标记废弃 · 保持不变"),
            ("[停止请求] 用户点击停止或按下B键", "正在停止…")):
        if text == source:
            return replacement, tag
    return text, tag
