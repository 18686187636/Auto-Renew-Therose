def click_order_now(sb):
    # 增加固定延时 5 秒，确保页面稳定，减少连接错误
    time.sleep(5)

    # 优先使用指定的 XPath（绝对路径）
    try:
        wait = WebDriverWait(sb.driver, 20)
        element = wait.until(EC.presence_of_element_located((By.XPATH, "/html/body/div/section/div/div[1]/form/div[1]/div[2]/div/div[2]/div[6]/button")))
        if element is not None:
            print("✅ 找到 Order now 按钮 (XPath)")
            sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            sb.driver.execute_script("arguments[0].click();", element)
            print("✅ 点击 Order now 成功 (XPath)")
            return True, ""
    except Exception as e:
        print(f"⚠️ 通过 XPath 点击失败: {e}")

    # 备选1：button:contains("Order now")
    try:
        sb.click('button:contains("Order now")', timeout=5)
        print("✅ 点击 Order now 成功 (button:contains)")
        return True, ""
    except Exception as e:
        print(f"⚠️ button:contains 失败: {e}")

    # 备选2：遍历所有按钮
    try:
        buttons = sb.find_elements('button')
        for btn in buttons:
            if btn is None:
                continue
            text = btn.text.strip().lower()
            if 'order now' in text or 'order' in text:
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn.webelement)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", btn.webelement)
                print("✅ 通过遍历点击 Order now 成功")
                return True, ""
    except Exception as e:
        print(f"⚠️ 遍历按钮失败: {e}")

    return False, "未找到 Order now 按钮"
