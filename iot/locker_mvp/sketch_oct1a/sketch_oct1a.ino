#include <WiFi.h>
#include <HTTPClient.h>
#include <Keypad.h>
#include <ESP32Servo.h>

// =====================
// WLAN
// =====================
const char* ssid = "Wlan SSID";
const char* password = "password";

// Dein Laptop
const char* backendUrl =
  "http://172.30.1.47:8000/locker/validate";

// =====================
// KEYPAD
// =====================
const byte ROWS = 4;
const byte COLS = 4;

char keys[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};

byte rowPins[ROWS] = {23, 22, 21, 19};
byte colPins[COLS] = {18, 17, 16, 4};

Keypad keypad = Keypad(
  makeKeymap(keys),
  rowPins,
  colPins,
  ROWS,
  COLS
);

// =====================
// SERVO
// =====================
Servo lockerServo;

const int SERVO_PIN = 26;
const int SERVO_CLOSED_ANGLE = 0;
const int SERVO_OPEN_ANGLE = 90;

// =====================
// CODE-EINGABE
// =====================
String enteredCode = "";

void setup() {

  Serial.begin(115200);

  // Servo
  lockerServo.setPeriodHertz(50);
  lockerServo.attach(SERVO_PIN, 500, 2400);
  lockerServo.write(SERVO_CLOSED_ANGLE);

  // WLAN
  Serial.print("Verbinde mit WLAN");

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WLAN verbunden!");
  Serial.println("Locker bereit.");
  Serial.println("Code eingeben und # druecken.");
}

void loop() {

  char key = keypad.getKey();

  if (!key) {
    return;
  }

  // Zahlen sammeln
  if (key >= '0' && key <= '9') {

    enteredCode += key;

    Serial.print("*");
  }

  // * = Eingabe löschen
  else if (key == '*') {

    enteredCode = "";

    Serial.println();
    Serial.println("Eingabe geloescht.");
  }

  // # = ans Backend schicken
  else if (key == '#') {

    Serial.println();
    Serial.print("Sende Code ans Backend... ");

    validateCode(enteredCode);

    enteredCode = "";
  }
}


// =====================
// BACKEND REQUEST
// =====================
void validateCode(String code) {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("Kein WLAN!");
    return;
  }

  HTTPClient http;

  http.begin(backendUrl);
  http.addHeader("Content-Type", "application/json");

  String body =
    "{\"device_id\":\"locker_01\",\"code\":\""
    + code +
    "\"}";

  int responseCode = http.POST(body);

  if (responseCode > 0) {

    String response = http.getString();

    Serial.print("HTTP ");
    Serial.println(responseCode);

    Serial.print("Backend: ");
    Serial.println(response);

    // Minimaler MVP:
    // Antwort enthält authorized:true
    if (response.indexOf("\"authorized\":true") >= 0) {

      Serial.println("ZUGRIFF ERLAUBT -> Servo oeffnet");

      lockerServo.write(SERVO_OPEN_ANGLE);

      delay(3000);

      lockerServo.write(SERVO_CLOSED_ANGLE);

      Serial.println("Locker wieder geschlossen.");
    }

    else {

      Serial.println("ZUGRIFF ABGELEHNT");
    }
  }

  else {

    Serial.print("Backend nicht erreichbar. Fehler: ");
    Serial.println(responseCode);
  }

  http.end();
}