
package com.example.appium;

import io.appium.java_client.AppiumBy;
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.options.UiAutomator2Options;
import io.appium.java_client.android.AndroidDriver;
import org.junit.jupiter.api.*;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.ui.WebDriverWait;
import org.openqa.selenium.support.ui.ExpectedConditions;

import java.net.URL;
import java.time.Duration;

@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class BasicAppiumTest {

    private static AndroidDriver driver;
    private static WebDriverWait wait;

    @BeforeAll
    static void setUp() throws Exception {
        UiAutomator2Options opts = new UiAutomator2Options()
                .setPlatformName("Android")
                .setAutomationName("UiAutomator2")
                .setDeviceName("Android Emulator")         // 실제 기기면 적절히 수정
       		.amend("noReset", true)
       		.amend("dontStopAppOnReset", true);


        driver = new AndroidDriver(new URL("http://127.0.0.1:4723"), opts);
        driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(2)); // 짧게
        wait = new WebDriverWait(driver, Duration.ofSeconds(15));
    }

    @AfterAll
    static void tearDown() {
        if (driver != null) driver.quit();
    }

    @Test
    @Order(1)
    void tapGoogleContinueByXpath() {
        // 대상 XPath
        String googleContinueXpath = "//android.widget.ImageView[@content-desc=\"Google로 계속하기\"]";

        // 보일 때까지 대기 후 탭
        WebElement googleBtn = wait.until(
                ExpectedConditions.elementToBeClickable(AppiumBy.xpath(googleContinueXpath)));
        googleBtn.click();

        // (선택) 클릭 후 전환 검증 로직 추가 가능
        // e.g., 다음 화면의 특정 요소가 보이는지 확인 등
        // WebElement next = wait.until(ExpectedConditions.visibilityOfElementLocated(
        //     AppiumBy.id("com.cureloop.mobile:id/some_next_view")));
        // Assertions.assertTrue(next.isDisplayed());
    }
}
