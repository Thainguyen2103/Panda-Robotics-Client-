#ifndef ROBOT_MOTOR_H
#define ROBOT_MOTOR_H

#include <Arduino.h>
#include "Config.h"

#ifdef HAS_ARM
#include <ESP32Servo.h>
static Servo armServo;
#endif

// ================================================================
//  KHỞI TẠO PHẦN CỨNG ĐỘNG CƠ & CẢM BIẾN
// ================================================================
static void initRobotHardware() {
  // Motor driver
  pinMode(PIN_PWMA, OUTPUT);
  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_PWMB, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);

  // Dừng động cơ ban đầu
  digitalWrite(PIN_AIN1, LOW); digitalWrite(PIN_AIN2, LOW);
  digitalWrite(PIN_BIN1, LOW); digitalWrite(PIN_BIN2, LOW);
  analogWrite(PIN_PWMA, 0);    analogWrite(PIN_PWMB, 0);

  // Buzzer & Nút nhấn
  pinMode(PIN_BUZZ, OUTPUT);
  digitalWrite(PIN_BUZZ, LOW);
  pinMode(PIN_BTN, INPUT_PULLUP);

  // Cảm biến siêu âm
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);

#ifdef HAS_ARM
  armServo.attach(PIN_SERVO);
  armServo.write(90);
#endif
}

// ================================================================
//  ĐIỀU KHIỂN ĐỘNG CƠ L298N / TB6612
// ================================================================
static void setMotorOutput(bool fwd, bool bwd, bool left, bool right, int speed = 200) {
  int a1 = fwd ? HIGH : LOW, a2 = bwd ? HIGH : LOW;
  int b1 = fwd ? HIGH : LOW, b2 = bwd ? HIGH : LOW;

  // Rẽ trái: Bánh trái lùi, bánh phải tiến
  if (left)  { a1 = LOW; a2 = HIGH; b1 = HIGH; b2 = LOW; }
  // Rẽ phải: Bánh trái tiến, bánh phải lùi
  if (right) { a1 = HIGH; a2 = LOW; b1 = LOW; b2 = HIGH; }

  digitalWrite(PIN_AIN1, a1); digitalWrite(PIN_AIN2, a2);
  digitalWrite(PIN_BIN1, b1); digitalWrite(PIN_BIN2, b2);

  int activeSpeed = (fwd || bwd || left || right) ? constrain(speed, 0, 255) : 0;
  analogWrite(PIN_PWMA, activeSpeed);
  analogWrite(PIN_PWMB, activeSpeed);
}

static void handleMoveCmd(String cmd, int speed = 200) {
  cmd.toLowerCase();
  if (cmd == "forward" || cmd == "fwd")      setMotorOutput(true, false, false, false, speed);
  else if (cmd == "back" || cmd == "bwd")    setMotorOutput(false, true, false, false, speed);
  else if (cmd == "left")                    setMotorOutput(false, false, true, false, speed);
  else if (cmd == "right")                   setMotorOutput(false, false, false, true, speed);
  else                                       setMotorOutput(false, false, false, false, 0);

  Serial.println("[MOTOR] Direction: " + cmd + " (Speed: " + String(speed) + ")");
}

// ================================================================
//  CẢM BIẾN SIÊU ÂM (ĐO KHOẢNG CÁCH VẬT CẢN)
// ================================================================
static long readUltrasonicDistance() {
#ifndef USE_MQTT
  // Trên Wokwi mô phỏng bằng Potentiometer GPIO 34
  int potVal = analogRead(PIN_POT);
  return map(potVal, 0, 4095, 4, 400);
#else
  // Trên ESP32 thật đo bằng sóng siêu âm HC-SR04
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  long duration = pulseIn(PIN_ECHO, HIGH, 30000); // Timeout 30ms (~5m)
  if (duration == 0) return 400; // Không có vật cản
  return (long)(duration * 0.0343 / 2);
#endif
}

// ================================================================
//  ĐIỀU KHIỂN CÒI BUZZER & TAY SERVO
// ================================================================
static void setBuzzer(bool on) {
  digitalWrite(PIN_BUZZ, on ? HIGH : LOW);
}

static void buzzTone(int freqHz, int durationMs) {
  tone(PIN_BUZZ, freqHz, durationMs);
}

static void handleArmCmd(String cmd) {
#ifdef HAS_ARM
  cmd.toLowerCase();
  if (cmd == "wave") {
    for (int i = 0; i < 3; i++) {
      armServo.write(20);  delay(250);
      armServo.write(90);  delay(250);
    }
  } else if (cmd == "up") {
    armServo.write(30);
  } else if (cmd == "down") {
    armServo.write(120);
  } else {
    armServo.write(90);
  }
#endif
  Serial.println("[ARM] Command: " + cmd);
}

#endif // ROBOT_MOTOR_H
