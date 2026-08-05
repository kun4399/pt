#!/usr/bin/env python3
"""
TJUPT 自动签到脚本
使用本地 Tesseract OCR 识别电影海报文字，匹配选项后自动签到。

依赖:
    - tjupt_login.py (同目录)
    - tesseract + chi_sim 语言包 (conda 环境)
    - pytesseract, Pillow, requests
"""

import io
import os
import re
import sys

import requests
from PIL import Image, ImageFilter, ImageEnhance
import pytesseract

# 确保能 import 同目录的 tjupt_login
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

# 设置 tesseract 路径 (conda 环境)
_tesseract_path = os.path.join(
    os.path.dirname(sys.executable), "tesseract"
)
if os.path.exists(_tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = _tesseract_path

from tjupt_login import login, BASE_URL

MAX_RETRIES = 10

# ── OCR ────────────────────────────────────────────────────────────

def preprocess_image(img: Image.Image) -> list:
    """
    预处理海报图片，返回多种预处理变体以提高 OCR 识别率。
    海报只有 270x405，文字可能风格化严重，多路尝试。
    """
    variants = []

    if img.mode == "RGBA":
        img = img.convert("RGB")

    # 变体 1: 4x 放大 + 灰度 + 对比度增强
    w, h = img.size
    v1 = img.resize((w * 4, h * 4), Image.LANCZOS).convert("L")
    v1 = ImageEnhance.Contrast(v1).enhance(2.0)
    variants.append(("4x_gray_contrast", v1))

    # 变体 2: 3x 放大 + 灰度 + 锐化
    v2 = img.resize((w * 3, h * 3), Image.LANCZOS).convert("L")
    v2 = v2.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=2))
    variants.append(("3x_gray_sharpen", v2))

    # 变体 3: 原始大小 + 灰度 + 自动对比度
    v3 = img.convert("L")
    from PIL import ImageOps
    v3 = ImageOps.autocontrast(v3, cutoff=5)
    variants.append(("original_autocontrast", v3))

    return variants


def ocr_poster(session: requests.Session, poster_url: str) -> str:
    """下载海报图片并执行 OCR，返回识别文字。"""
    resp = session.get(poster_url, timeout=15)
    img = Image.open(io.BytesIO(resp.content))

    # 多路预处理
    variants = preprocess_image(img)

    # 多模式 OCR: 对每个预处理变体尝试不同 PSM
    all_texts = []
    for variant_name, processed in variants:
        for psm in [6, 11]:
            try:
                text = pytesseract.image_to_string(
                    processed, lang="chi_sim+eng", config=f"--psm {psm} --oem 1"
                )
                if text.strip():
                    all_texts.append(text.strip())
            except Exception as e:
                print(f"    OCR ({variant_name}/PSM{psm}) 出错: {e}")

    combined = "\n".join(all_texts)
    return combined

# ── 匹配 ────────────────────────────────────────────────────────────

def match_option(ocr_text: str, options: list) -> tuple:
    """
    将 OCR 文字与选项进行多策略匹配。

    策略:
    1. 逐字匹配: 选项的每个字符是否在 OCR 文字中出现
    2. 子串匹配: 选项的连续 2-3 字片段是否在 OCR 中出现
    3. 综合打分

    Returns:
        (best_match, all_scores)
    """
    if not ocr_text:
        return None, []

    # 归一化
    ocr_normalized = ocr_text.replace(" ", "").replace("\n", "")
    ocr_chars = set(ocr_normalized)

    scores = []
    for value, label in options:
        label_clean = label.replace(" ", "")
        label_chars = set(label_clean)
        label_len = len(label_clean)

        if label_len == 0:
            scores.append((value, label, 0.0, 0.0, 0.0))
            continue

        # 1. 逐字匹配分数
        char_matched = label_chars & ocr_chars
        char_score = len(char_matched) / len(label_chars)

        # 2. 子串匹配分数 (2-gram 和 3-gram)
        substring_bonus = 0.0
        for n in [3, 2]:  # 先检查长片段
            for i in range(label_len - n + 1):
                sub = label_clean[i:i+n]
                if sub in ocr_normalized:
                    substring_bonus += n / label_len
                    break  # 找到一个长片段就够了
            if substring_bonus > 0:
                break

        # 综合分数: 字符匹配 + 子串奖励
        combined_score = char_score + substring_bonus * 0.5
        # 上限 1.0
        combined_score = min(combined_score, 1.0)

        scores.append((value, label, combined_score, char_score, substring_bonus))

    scores.sort(key=lambda x: x[2], reverse=True)

    best = scores[0]
    second = scores[1] if len(scores) > 1 else ("", "", 0.0, 0.0, 0.0)

    # 阈值判断
    best_score = best[2]
    second_score = second[2]

    # 需要最佳分数 >= 0.4 且明显优于第二候选
    if best_score >= 0.4 and (best_score >= 1.0 or best_score > second_score * 1.5):
        return (best[0], best[1], best_score), [(v, l, s) for v, l, s, _, _ in scores]

    return None, [(v, l, s) for v, l, s, _, _ in scores]

# ── 页面解析 ────────────────────────────────────────────────────────

def get_attendance_page(session: requests.Session) -> dict:
    """
    获取签到页面，解析海报 URL 和选项。

    Returns:
        {
            "status": "ok" | "already_signed" | "error",
            "poster_url": str | None,
            "options": [(value, label), ...] | [],
            "message": str,
        }
    """
    try:
        resp = session.get(f"{BASE_URL}/attendance.php", timeout=15)
    except requests.RequestException as e:
        return {"status": "error", "poster_url": None, "options": [], "message": str(e)}

    html = resp.text

    # 已签到检测: 没有 ban_robot 表单 → 可能已签到
    if "ban_robot" not in html:
        # 确认是否有已签到消息
        if "今日已签到" in html:
            detail = re.search(
                r'已累计签到\s*(\d+)\s*次.*?已连续签到\s*(\d+)\s*天.*?获得了\s*(\d+)\s*个?\s*魔力值',
                html
            )
            if detail:
                return {"status": "already_signed", "poster_url": None, "options": [],
                        "message": f"今日已签到 (累计 {detail.group(1)} 次, "
                                   f"连续 {detail.group(2)} 天, +{detail.group(3)} 魔力值)"}
            return {"status": "already_signed", "poster_url": None, "options": [],
                    "message": "今日已签到"}
        # 可能被重定向到登录页
        if "login" in resp.url.lower() or "takelogin" in resp.url.lower():
            return {"status": "error", "poster_url": None, "options": [],
                    "message": "登录已过期，需要重新登录"}
        return {"status": "already_signed", "poster_url": None, "options": [],
                "message": "未找到签到表单，可能已签到"}

    # 提取海报 URL
    poster_match = re.search(r"<img src='(/pic/attend/[^']+)'", html)
    if not poster_match:
        return {"status": "error", "poster_url": None, "options": [],
                "message": "未找到海报图片"}

    poster_url = BASE_URL + poster_match.group(1)

    # 提取选项: label 内的 radio + 文字
    options = []
    for match in re.finditer(
        r"<input type='radio' name='ban_robot' value='([^']+)'>([^<]+)",
        html
    ):
        options.append((match.group(1), match.group(2).strip()))

    if not options:
        return {"status": "error", "poster_url": poster_url, "options": [],
                "message": "未找到签到选项"}

    return {"status": "ok", "poster_url": poster_url, "options": options,
            "message": f"找到 {len(options)} 个选项"}

# ── 提交 ────────────────────────────────────────────────────────────

def submit_answer(session: requests.Session, option_value: str) -> requests.Response:
    """提交签到答案。"""
    return session.post(
        f"{BASE_URL}/attendance.php",
        data={"ban_robot": option_value, "submit": "提交"},
        timeout=15,
    )

# ── 主流程 ──────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("TJUPT 自动签到")
    print("=" * 50)

    # ── 登录 ──
    print("\n[登录]")
    session = login(verbose=True)
    if not session:
        print("✗ 登录失败，退出")
        sys.exit(1)

    # ── 签到循环 ──
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n{'─' * 30}")
        print(f"[签到] 第 {attempt}/{MAX_RETRIES} 次尝试")

        # 获取签到页
        result = get_attendance_page(session)

        if result["status"] == "already_signed":
            print(f"  ✓ {result['message']}")
            return

        if result["status"] == "error":
            print(f"  ✗ {result['message']}")
            if "登录已过期" in result["message"]:
                print("  重新登录...")
                session = login(verbose=True)
                if not session:
                    print("  ✗ 重新登录失败")
                    sys.exit(1)
                continue
            return

        poster_url = result["poster_url"]
        options = result["options"]

        print(f"  海报: ...{poster_url[-40:]}")
        print(f"  选项 ({len(options)} 个):")
        for i, (v, label) in enumerate(options):
            print(f"    [{i+1}] {label}")

        # OCR 识别
        print(f"  OCR 识别中...", end=" ", flush=True)
        try:
            ocr_text = ocr_poster(session, poster_url)
        except Exception as e:
            print(f"\n  ✗ OCR 异常: {e}")
            print("  换题重试...")
            continue

        if ocr_text:
            # 截断显示
            display = ocr_text[:150].replace("\n", " / ")
            print(f"\"{display}{'...' if len(ocr_text) > 150 else ''}\"")
        else:
            print("(无文字)")
            print("  ~ OCR 无结果，换题重试...")
            continue

        # 匹配
        best_match, all_scores = match_option(ocr_text, options)

        print(f"  匹配:")
        for v, label, score in all_scores:
            bar = "█" * int(score * 20)
            marker = " ★" if best_match and v == best_match[0] else ""
            print(f"    {label:20s} {bar:20s} {score:.0%}{marker}")

        if best_match:
            value, label, score = best_match
            print(f"\n  → 选中: \"{label}\" (置信度 {score:.0%})")
            print(f"  提交中...", end=" ", flush=True)

            try:
                resp = submit_answer(session, value)
            except requests.RequestException as e:
                print(f"\n  ✗ 提交失败: {e}")
                continue

            # 检查结果
            resp_text = resp.text

            # 成功: "今日获得了 X 个魔力值"
            success_match = re.search(
                r'(?:获得了|签到成功).*?(\d+)\s*个?\s*魔力值', resp_text
            )
            if success_match or "获得了" in resp_text and "魔力值" in resp_text:
                # 提取详细信息
                detail = re.search(
                    r'已累计签到\s*(\d+)\s*次.*?已连续签到\s*(\d+)\s*天.*?获得了\s*(\d+)\s*个?\s*魔力值',
                    resp_text
                )
                if detail:
                    print(f"✓ 签到成功！累计 {detail.group(1)} 次，"
                          f"连续 {detail.group(2)} 天，+{detail.group(3)} 魔力值")
                else:
                    print("✓ 签到成功！获得魔力值")
                return

            # 错误
            if "回答错误" in resp_text:
                print("✗ 答案错误，换题重试...")
                continue

            # 已签到 (通常是刷新后出现，或者重复提交)
            if "今日已签到" in resp_text or "已经签到" in resp_text:
                detail = re.search(
                    r'已累计签到\s*(\d+)\s*次.*?已连续签到\s*(\d+)\s*天.*?获得了\s*(\d+)\s*个?\s*魔力值',
                    resp_text
                )
                if detail:
                    print(f"✓ 今日已签到 (累计 {detail.group(1)} 次, "
                          f"+{detail.group(3)} 魔力值)")
                else:
                    print("✓ 今日已签到")
                return

            # 页面还有表单 → 答案未被接受 (可能返回了新题或同一题)
            if "ban_robot" in resp_text:
                print("✗ 答案未被接受，换题重试...")
                continue

            # 未知响应 - 保存以便调试
            print("? 响应未识别，保存到 /tmp/tjupt_sign_response.html")
            with open("/tmp/tjupt_sign_response.html", "w") as f:
                f.write(resp_text)
            return
        else:
            print(f"  ~ 无可靠匹配 (最高 {all_scores[0][1]}: {all_scores[0][2]:.0%})")
            print("  换题重试...")

    print(f"\n{'=' * 50}")
    print(f"✗ 超过最大重试次数 ({MAX_RETRIES})，签到失败")
    print(f"  建议手动签到: {BASE_URL}/attendance.php")
    sys.exit(1)


if __name__ == "__main__":
    main()
