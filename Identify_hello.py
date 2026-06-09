import cv2

THRESHOLD = 0.42  # 低于此值视为不存在

# 1. 读取原图(大图) 和 模板图(要查找的小图)
img = cv2.imread("img/4.png")
template = cv2.imread("templates/nihao.png")

if img is None or template is None:
    print("图片读取失败，请检查文件路径！")
    exit()

h, w = template.shape[:2]

# 2. 灰度匹配
img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
res = cv2.matchTemplate(img_gray, template_gray, cv2.TM_CCOEFF_NORMED)

# 3. 获取最高匹配度
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
top_left = max_loc
bottom_right = (top_left[0] + w, top_left[1] + h)

# 4. 输出置信度
print(f"[nihao] 最高置信度: {max_val:.4f}  位置: {top_left}  阈值: {THRESHOLD}")

# 5. 只在超过阈值时画框
if max_val >= THRESHOLD:
    cv2.rectangle(img, top_left, bottom_right, (0, 255, 0), 2)
    label = f"nihao {max_val:.3f} (MATCH)"
    color = (0, 255, 0)
else:
    # 低于阈值也画红色虚线框，标注为无效
    cv2.rectangle(img, top_left, bottom_right, (0, 0, 255), 1)
    label = f"nihao {max_val:.3f} (NOISE)"
    color = (0, 0, 255)

cv2.putText(img, label, (top_left[0], top_left[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

print(f"[结果] {'匹配成功' if max_val >= THRESHOLD else '背景噪点，不存在nihao'}")

cv2.imshow("Identify nihao", img)
cv2.imshow("Template", template)
cv2.waitKey(0)
cv2.destroyAllWindows()

cv2.imwrite("result.jpg", img)
