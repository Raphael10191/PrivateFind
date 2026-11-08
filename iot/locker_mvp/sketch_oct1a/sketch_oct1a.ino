#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include <ESP32Servo.h>

#include "../secrets.h"

// Current breadboard wiring. Only compartment 1 exists.
const int LCD_SDA_PIN = 27;
const int LCD_SCL_PIN = 14;
const int ULTRASONIC_TRIGGER_PIN = 33;
const int ULTRASONIC_ECHO_PIN = 25;
const int IR_SENSOR_PIN = 34;
const int SERVO_PIN = 26;

const int SERVO_CLOSED_ANGLE = 0;
const int SERVO_OPEN_ANGLE = 90;
const float ITEM_DISTANCE_THRESHOLD_CM = 15.0f;
const unsigned long SENSOR_REFRESH_MS = 250;
const unsigned long WIFI_RETRY_MS = 10000;
const byte REQUIRED_STABLE_SAMPLES = 4;

LiquidCrystal_I2C lcd(0x27, 16, 2);
Servo lockerServo;

const byte ROWS = 4;
const byte COLS = 4;
char keys[ROWS][COLS] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};
byte rowPins[ROWS] = {23, 22, 21, 19};
byte colPins[COLS] = {18, 17, 16, 4};
Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

enum LockerMode { ENTER_CODE, DOOR_OPEN, VERIFYING_STATE };
enum Occupancy { SENSOR_UNKNOWN = -1, EMPTY = 0, OCCUPIED = 1 };

LockerMode lockerMode = ENTER_CODE;
String enteredCode = "";
String activeAction = "";
unsigned long lastSensorRead = 0;
unsigned long lastWifiRetry = 0;
Occupancy candidateState = SENSOR_UNKNOWN;
byte stableSamples = 0;
float lastDistanceCm = -1;


void setup() {
  Serial.begin(115200);
  initializeHardware();
  connectWifi();
  showStatus("Code eingeben");
}


void loop() {
  keepWifiConnected();
  refreshSensors();
  handleKeypad();
}


void initializeHardware() {
  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN);
  lcd.init();
  lcd.backlight();
  lcd.clear();

  pinMode(ULTRASONIC_TRIGGER_PIN, OUTPUT);
  pinMode(ULTRASONIC_ECHO_PIN, INPUT);
  pinMode(IR_SENSOR_PIN, INPUT);
  digitalWrite(ULTRASONIC_TRIGGER_PIN, LOW);

  lockerServo.setPeriodHertz(50);
  lockerServo.attach(SERVO_PIN, 500, 2400);
  lockerServo.write(SERVO_CLOSED_ANGLE);
}


void connectWifi() {
  lcd.setCursor(0, 0);
  lcd.print("WLAN verbindet");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 10000) {
    delay(250);
    Serial.print('.');
  }

  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WLAN verbunden.");
  } else {
    Serial.println("WLAN Fehler. Neuer Versuch folgt.");
    showStatus("WLAN Fehler");
  }
}


void keepWifiConnected() {
  if (WiFi.status() == WL_CONNECTED || millis() - lastWifiRetry < WIFI_RETRY_MS) {
    return;
  }

  lastWifiRetry = millis();
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("WLAN-Verbindung wird erneut versucht.");
}


void handleKeypad() {
  char key = keypad.getKey();
  if (!key) {
    return;
  }

  Serial.printf("Taste erkannt: %c\n", key);

  if (lockerMode == DOOR_OPEN) {
    if (key == '#') {
      beginStateVerification();
    }
    return;
  }

  if (lockerMode == VERIFYING_STATE) {
    return;
  }

  if (key >= '0' && key <= '9') {
    if (enteredCode.length() < 12) {
      enteredCode += key;
      showStatus("Code: " + maskedCode());
    }
    return;
  }

  if (key == '*') {
    enteredCode = "";
    showStatus("Eingabe geloescht");
    return;
  }

  if (key == '#' && enteredCode.length() > 0) {
    String action = "";
    bool authorized = validateCodeWithBackend(enteredCode, action);
    enteredCode = "";

    if (authorized) {
      openCompartment(action);
    } else {
      showStatus("Zugriff abgelehnt");
    }
  }
}


bool validateCodeWithBackend(const String& code, String& action) {
  if (WiFi.status() != WL_CONNECTED) {
    showStatus("WLAN nicht bereit");
    return false;
  }

  showStatus("Code wird geprueft");
  HTTPClient http;
  http.begin(BACKEND_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);

  String body = "{\"device_id\":\"locker_01\",\"code\":\"" + code + "\"}";
  int responseCode = http.POST(body);
  String response = responseCode > 0 ? http.getString() : "";
  http.end();

  Serial.printf("Code-API: HTTP %d\n", responseCode);
  Serial.println(response);

  if (responseCode != HTTP_CODE_OK ||
      response.indexOf("\"authorized\":true") < 0 ||
      response.indexOf("\"compartment\":1") < 0) {
    return false;
  }

  if (response.indexOf("\"action\":\"deposit\"") >= 0) {
    action = "deposit";
    return true;
  }
  if (response.indexOf("\"action\":\"pickup\"") >= 0) {
    action = "pickup";
    return true;
  }
  return false;
}


void openCompartment(const String& action) {
  activeAction = action;
  lockerServo.write(SERVO_OPEN_ANGLE);
  lockerMode = DOOR_OPEN;

  if (action == "deposit") {
    showStatus("Item rein, dann #");
  } else {
    showStatus("Item raus, dann #");
  }
  Serial.println("Fach 1 offen. Nach dem Schliessen # druecken.");
}


// The user closes the physical door, then presses #. Only then do we report state.
void beginStateVerification() {
  lockerMode = VERIFYING_STATE;
  candidateState = SENSOR_UNKNOWN;
  stableSamples = 0;
  showStatus("Sensor pruefen...");
  Serial.println("Pruefe beide Sensoren vor dem Schliessen.");
}


void refreshSensors() {
  if (millis() - lastSensorRead < SENSOR_REFRESH_MS) {
    return;
  }
  lastSensorRead = millis();

  lastDistanceCm = readDistanceCm();
  renderSensorLine(lastDistanceCm);

  if (lockerMode == VERIFYING_STATE) {
    verifyAndReportState(lastDistanceCm);
  }
}


float readDistanceCm() {
  digitalWrite(ULTRASONIC_TRIGGER_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIGGER_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIGGER_PIN, LOW);

  unsigned long duration = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000);
  return duration == 0 ? -1 : duration * 0.0343f / 2.0f;
}


void renderSensorLine(float distance) {
  lcd.setCursor(0, 0);
  lcd.print("                ");
  lcd.setCursor(0, 0);
  if (distance < 0) {
    lcd.print("Dist: -- cm");
  } else {
    lcd.print("Dist:");
    lcd.print(distance, 1);
    lcd.print("cm");
  }
}


// A state is trusted only if IR and ultrasound agree for four readings.
void verifyAndReportState(float distance) {
  Occupancy observation = readConfirmedOccupancy(distance);
  if (observation == SENSOR_UNKNOWN) {
    candidateState = SENSOR_UNKNOWN;
    stableSamples = 0;
    showStatus("Sensoren pruefen");
    return;
  }

  if (observation != candidateState) {
    candidateState = observation;
    stableSamples = 1;
  } else {
    stableSamples++;
  }

  if (stableSamples < REQUIRED_STABLE_SAMPLES) {
    showStatus("Messung bestaetigen");
    return;
  }

  bool occupied = candidateState == OCCUPIED;
  if (reportCompartmentState(occupied)) {
    lockerServo.write(SERVO_CLOSED_ANGLE);
    lockerMode = ENTER_CODE;
    activeAction = "";
    showStatus(occupied ? "Item sicher drin" : "Fach ist leer");
    Serial.println("Status gesendet. Fach 1 geschlossen.");
  } else {
    showStatus("Backend Fehler");
  }
}


Occupancy readConfirmedOccupancy(float distance) {
  if (distance < 0) {
    return SENSOR_UNKNOWN;
  }

  // Most IR obstacle modules return LOW when they detect an object.
  bool irSeesItem = digitalRead(IR_SENSOR_PIN) == LOW;
  bool ultrasonicSeesItem = distance <= ITEM_DISTANCE_THRESHOLD_CM;

  if (irSeesItem != ultrasonicSeesItem) {
    Serial.println("Sensoren sind nicht einig.");
    return SENSOR_UNKNOWN;
  }
  return irSeesItem ? OCCUPIED : EMPTY;
}


bool reportCompartmentState(bool occupied) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  HTTPClient http;
  http.begin(BACKEND_STATE_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);

  String body = "{\"device_id\":\"locker_01\",\"occupied\":";
  body += occupied ? "true}" : "false}";
  int responseCode = http.POST(body);
  String response = responseCode > 0 ? http.getString() : "";
  http.end();

  Serial.printf("Status-API: HTTP %d\n", responseCode);
  Serial.println(response);
  return responseCode == HTTP_CODE_OK;
}


void showStatus(const String& message) {
  lcd.setCursor(0, 1);
  lcd.print("                ");
  lcd.setCursor(0, 1);
  lcd.print(message.substring(0, 16));
}


String maskedCode() {
  String mask = "";
  for (unsigned int i = 0; i < enteredCode.length(); i++) {
    mask += '*';
  }
  return mask;
}
