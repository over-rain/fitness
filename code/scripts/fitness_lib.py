# -*- coding: utf-8 -*-
"""fitness_lib.py —— 热量/宏量/BMI 计算（Mifflin-St Jeor）。只做纯计算，不读文件。"""
import json
import sys


def bmr(height_cm, weight_kg, age, gender):
    if gender in ("male", "男", "m", "male"):
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161


ACTIVITY = {  # Excel: 周训练天数 -> 活动系数（约）
    0: 1.2, 1: 1.26, 2: 1.32, 3: 1.38, 4: 1.44, 5: 1.5, 6: 1.56, 7: 1.6,
}
GOAL_DELTA = {"fat_loss": -350, "bulk": 250, "maintain": 0}


def plan(height_cm, weight_kg, age, gender, goal="fat_loss", training_days=4, deficit=None):
    total = weight_kg * 10 + height_cm * 6.25 - 5 * age + (5 if gender in ("male", "男") else -161)
    b = total
    a = ACTIVITY.get(int(training_days), 1.35)
    tdee = round(b * a)
    if deficit is not None:
        goal_kcal = tdee - int(deficit)
    else:
        goal_kcal = tdee + GOAL_DELTA.get(goal, 0)
    protein_g = round(weight_kg * (1.6 if goal == "fat_loss" else 1.8))
    fat_g = round(weight_kg * 0.8)
    # 减脂期蛋白占比高，其余给碳水
    remaining = goal_kcal - protein_g * 4 - fat_g * 9
    carb_g = round(remaining / 4)
    bmi = round(weight_kg / (height_cm / 100) ** 2, 1)
    return {
        "height_cm": height_cm, "weight_kg": weight_kg, "age": age, "gender": gender,
        "goal": goal, "training_days": training_days,
        "bmr": b, "activity_factor": a, "tdee": tdee,
        "target_kcal": goal_kcal, "protein_g": protein_g, "fat_g": fat_g, "carb_g": carb_g, "bmi": bmi,
    }


def fmt(p: dict) -> str:
    goal = {"fat_loss": "减脂", "bulk": "增肌", "maintain": "保持"}.get(p["goal"], p["goal"])
    return (
        f"目标：{goal} | BMI {p['bmi']}\n"
        f"基础代谢 BMR：{p['bmr']} kcal\n"
        f"每日消耗 TDEE：{p['tdee']} kcal（活动系数 {p['activity_factor']}）\n"
        f"目标摄入：{p['target_kcal']} kcal/天\n"
        f"宏量：蛋白 {p['protein_g']}g | 脂肪 {p['fat_g']}g | 碳水 {p['carb_g']}g"
    )


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "calories"
    if cmd == "calories" and len(sys.argv) >= 7:
        h, w, age, g, goal, days = sys.argv[2:8]
        p = plan(float(h), float(w), int(age), g, goal, int(days))
        print(fmt(p))
    elif cmd == "info" and len(sys.argv) >= 4:
        h, w = float(sys.argv[2]), float(sys.argv[3])
        for age, g in [(25, "male"), (25, "female"), (35, "male")]:
            pass
        print("usage: plan() 或 calories <h> <w> <age> <gender> <goal> <days>")
    else:
        print("usage: python fitness_lib.py calories <height_cm> <weight_kg> <age> <sex:male|female> <goal:fat_loss|bulk|maintain> <training_days>")