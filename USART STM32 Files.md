---
type: software
status: active
---
ФАЙЛЫ USART У МИКРОКОНТРОЛЛЕРА STM32
-============================================================
Файл /src/usart1.h
-============================================================
Содержание 
#include "stm32f401xc.h"

#ifndef USART1_H
#define USART1_H

uint32_t usart1div;

void USART1_Init(uint32_t boudrate);
void USART1_SendArray(const uint8_t *data, uint16_t len);
	
#endif

-============================================================
Файл /src/usart1.c
-============================================================
Содержание 
#include "usart1.h"

uint32_t usart1div;

void USART1_Init(uint32_t boudrate) {
	RCC->APB2ENR |= RCC_APB2ENR_USART1EN;     // Включение тактирования USART1; f(APB2)=42МГц
	
	USART1->CR1 &= ~USART_CR1_UE;             //Выключение USART1 перед настройкой
	
	USART1->CR1 &= ~(USART_CR1_M | USART_CR1_PCE);     //8 бит данных, 1 старт-бит, без четности
  USART1->CR2 &= ~USART_CR2_STOP;                    //1 стоп-бит,
	usart1div = (16 * 42000000)/boudrate;              //Настройка делителя USART1 на необходимый бодрейт
	USART1->BRR = usart1div;                           
	USART1->CR1 |= (USART_CR1_RE | USART_CR1_RXNEIE);  //Включаем возможность принятия сообщения и прерывание по принятому сообщению
	USART1->CR1 |= USART_CR1_TE;                       //Включаем возможность отправки сообщения
	
	USART1->CR1 |= USART_CR1_UE;              //Включение USART1 после настройки
	
	NVIC_EnableIRQ(USART1_IRQn);       //Включение прерываний
  NVIC_SetPriority(USART1_IRQn, 1);  // Приоритет прерывания
}

void USART1_SendArray(const uint8_t *data, uint16_t len) {
    if (len == 0) {
        return;  // Защита от некорректных данных
    }
    
    for (uint16_t i = 0; i < len; i++) {
        // Ждём, пока регистр передачи освободится (TXE = 1)
        while (!(USART1->SR & USART_SR_TXE));
        
        // Записываем байт в регистр данных
        USART1->DR = data[i];
    }
    
    // Ждём полного завершения передачи (TC = 1)
    // Это важно для последнего байта, чтобы он успел уйти по линии
    while (!(USART1->SR & USART_SR_TC));
}

-============================================================
Файл /src/main.h (весь)
-============================================================
Содержание 
#include "stm32f401xc.h"
#include "stdbool.h"
#include "rcc.h"
#include "gpio.h"
#include "usart1.h"
#include "pwm.h"
#include "adc.h"
#include "dht22.h"

#ifndef MAIN_H
#define MAIN_H

//ЗАПИСАТЬ В ДЕФАЙНЫ ВСЕ ТАЙМАУТЫ (ИХ ПИЗДА МНОГО)
#define MAX_MESSAGE_LENGTH 20
#define BUFFER_LENGTH 10

#define PROTOCOL_SOURCE_msk 0b00000001
#define PROTOCOL_TYPE_COMMAND_TYPE_msk 0b00000110
#define PROTOCOL_TYPE_SENSOR_TYPE_msk 0b00111000

#define MESSAGE_STB 0
#define MESSAGE_TYPE 1
#define MESSAGE_LEN 2

#define HEATER_MAX_TEMPERATURE 20
#define HEATER_MIN_TEMPERATURE 10
#define COOLER_MAX_TEMPERATURE 35
#define COOLER_MIN_TEMPERATURE 15

#define AIR_SHUTTERS_OPEN_TIMEOUT 1000000 //Такты
#define AIR_SHUTTERS_CLOSE_TIMEOUT 1000000 //Такты
#define STEP_MOTOR_TABLE_UPPER_TIMEOUT 5000 // ... = steps/10
#define STEP_MOTOR_TABLE_LOWER_TIMEOUT 5000 // ... = steps/10
#define STEP_MOTOR_DRONE_HOLD_TIMEOUT 5000 // ... = steps/10
#define STEP_MOTOR_DRONE_OPEN_TIMEOUT 5000 // ... = steps/10
#define ROOF_SHUTTERS_OPEN_TIMEOUT 10000000 //Такты
#define ROOF_SHUTTERS_CLOSE_TIMEOUT 10000000 //Такты

uint8_t msg_tx[MAX_MESSAGE_LENGTH]; //Сообщение для отправки к микрокомпьютеру
uint8_t msg_rx[BUFFER_LENGTH][MAX_MESSAGE_LENGTH];
uint8_t start_msg_index = 0; //Индекс читаемого сообщения
uint8_t last_msg_index = 0; //Индекс последнего полученного и записанного сообщения
uint8_t msg_byte_index = 0; //Индекс последнего слова в сообщении
uint8_t msg_to_send[MAX_MESSAGE_LENGTH];
uint8_t msg_to_send_byte_index = 0;
bool isClimatic = 0; //Флаг включения климат контроля


#endif

-============================================================
Файл /src/main.c (весь)
-============================================================
Содержание 
#include "main.h"
#include "stdlib.h"
#include "stdint.h"
#include "stdio.h"

extern uint8_t msg_tx[MAX_MESSAGE_LENGTH]; //Сообщение для отправки к микрокомпьютеру
extern uint8_t msg_rx[BUFFER_LENGTH][MAX_MESSAGE_LENGTH];
extern uint8_t start_msg_index; //Индекс читаемого сообщения
extern uint8_t last_msg_index; //Индекс последнего полученного и записанного сообщения
extern uint8_t msg_byte_index; //Индекс последнего слова в сообщении
extern bool isClimatic; //Флаг включения климат контроля

void Airing_control(uint8_t sw) {
	switch (sw) {
		case 0:
			GPIOA->ODR |= (0b1<<11);
			GPIOA->ODR &= ~(0b1<<5);
			uint32_t counter = 0;
			while (counter <= AIR_SHUTTERS_OPEN_TIMEOUT && (GPIOB->IDR & (0b1<<4)) && (GPIOB->IDR & (0b1<<5))) counter++;
			GPIOA->ODR &= ~(0b1<<11);
			GPIOA->ODR &= ~(0b1<<1);
			break;
		case 1:
			GPIOA->ODR |= (0b1<<5);
			GPIOA->ODR &= ~(0b1<<11);
			delay(1500);
			GPIOA->ODR &= ~(0b1<<5);
			GPIOA->ODR |= 0b1<<1;
			break;
		default:
			break;
	}
}

void makeSteps(uint8_t params, uint32_t steps) {
	switch (params & 0b11) {
		case 0b00:                                      //Подъём стола
			GPIOB->ODR |= (0b1<<9); //ENA
			GPIOB->ODR |= (0b1<<10); //DIR
			for (uint32_t i = 0; i <= steps; i++) {
				GPIOB->ODR |= (0b1<<11); //step
				delayMicroseconds(50);
				GPIOB->ODR &= ~(0b1<<11); //step
				delayMicroseconds(50);
			}
			GPIOB->ODR &= ~(0b1<<11); //DIR
			GPIOB->ODR &= ~(0b1<<10); //ENA
			break;
		case 0b01:                                      //Опускание стола
			GPIOB->ODR |= (0b1<<9); //ENA
			GPIOB->ODR &= ~(0b1<<10); //DIR
			for (uint32_t i = 0; i <= steps; i++) {
				GPIOB->ODR |= (0b1<<11); //step
				delayMicroseconds(50);
				GPIOB->ODR &= ~(0b1<<11); //step
				delayMicroseconds(50);
			}
			GPIOB->ODR &= ~(0b1<<11); //DIR
			GPIOB->ODR &= ~(0b1<<10); //ENA
			break;
		case 0b10:                                       //Отпускание лапок дрона
			GPIOB->ODR |= (0b1<<13); //ENA
			GPIOB->ODR |= (0b1<<14); //DIR
			for (uint32_t i = 0; i <= steps; i++) {
				GPIOB->ODR |= (0b1<<15); //step
				delayMicroseconds(50);
				GPIOB->ODR &= ~(0b1<<15); //step
				delayMicroseconds(50);
			}
			GPIOB->ODR &= ~(0b1<<14); //DIR
			GPIOB->ODR &= ~(0b1<<13); //ENA
			break;
		case 0b11:                                        //Сжатие лапок дрона
			GPIOB->ODR |= (0b1<<13); //ENA
			GPIOB->ODR &= ~(0b1<<14); //DIR
			for (uint32_t i = 0; i <= steps; i++) {
				GPIOB->ODR |= (0b1<<15); //step
				delayMicroseconds(50);
				GPIOB->ODR &= ~(0b1<<15); //step
				delayMicroseconds(50);
			}
			GPIOB->ODR &= ~(0b1<<14); //DIR
			GPIOB->ODR &= ~(0b1<<13); //ENA
			break;
		default:
			break;
	}
}

uint8_t CRC_check(uint8_t *data, uint8_t length, uint8_t CRC_index) {
	uint8_t res = 0;
	for (int i = 0; i < length; i++) {
		if (i != CRC_index) res ^= data[i];
	}
	return (res == data[CRC_index]);
}

void read_message(void) {
	//Настройка основных параметров
	uint8_t len = msg_rx[start_msg_index][MESSAGE_LEN];
	uint8_t message[MAX_MESSAGE_LENGTH];
	for (int i = 0; i < MAX_MESSAGE_LENGTH; i++) message[i] = msg_rx[start_msg_index][i];
	//Проверка контрольной суммы 
	if (CRC_check(message, len+5, len+4)){
		if (message[MESSAGE_TYPE] & PROTOCOL_SOURCE_msk){ 
			//Прочтение сообщения
			switch ((message[MESSAGE_TYPE] & PROTOCOL_TYPE_COMMAND_TYPE_msk) >> 1) {
				case 0b00: //Запрос статуса
					switch ((message[MESSAGE_TYPE] & PROTOCOL_TYPE_SENSOR_TYPE_msk) >> 3) {
						case 0b001: //Датчики Холла
							msg_tx[0] = 0xFF;
							msg_tx[1] = 0b00001010;
							msg_tx[2] = 1;
							msg_tx[3] = ((GPIOB->IDR & (0b1<<0)) | 	  //Крыша открыта
													 (GPIOB->IDR & (0b1<<1)) | 	  //Крыша закрыта
													 (GPIOB->IDR & (0b1<<2)) | 	  //Стол поднят
													 (GPIOB->IDR & (0b1<<3)) | 	  //Стол опущен
													 (GPIOB->IDR & (0b1<<4)) | 	  //Вентиляция 1 закрыта
													 (GPIOB->IDR & (0b1<<5)) | 	  //Вентиляция 2 закрыта
													 (GPIOB->IDR & (0b1<<7))>>1); //Лапки дрона сжаты
							msg_tx[5] = 0b10111111;
							for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
							USART1_SendArray(msg_tx, msg_tx[2]+5);
							for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;						 
							break;
						case 0b010: //Напряжение АКБ
							msg_tx[0] = 0xFF;
							msg_tx[1] = 0b00010010;
							msg_tx[2] = 2;
							uint16_t voltage = ADC_ReadRaw();
							msg_tx[4] = voltage & 0xFF;
							msg_tx[3] = (voltage & 0xFF00)>>8;
							msg_tx[6] = 0b10111111;
							for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
							USART1_SendArray(msg_tx, msg_tx[2]+5);
							for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
							break;
						case 0b011: //DHT22 
							msg_tx[0] = 0xFF;
							msg_tx[1] = 0b00010010;
							msg_tx[2] = 5;
							uint8_t dht22_data[5] = {0, 0, 0, 0, 0};
							if (DHT22_Read(dht22_data)) {
								for (int i = 0; i < 5; i++) msg_tx[7-i] = dht22_data[i];
								msg_tx[9] = 0b10111111;
								for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
								USART1_SendArray(msg_tx, msg_tx[2]+5);
								for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
							} else { //Ошибка контрольной суммы
								msg_tx[0] = 0xFF;
								msg_tx[1] = 0b00000110;
								msg_tx[2] = 1;
								msg_tx[3] = 0;
								msg_tx[5] = 0b10111111;
								for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
								USART1_SendArray(msg_tx, msg_tx[2]+5);
								for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
							}
							break;
						default:
							break;
					}
					break;
				case 0b10: //Команда на действие
					switch (message[3]) {
						case 1: //Старт вибромотора
							GPIOA->ODR |= 0b1;
							break;
						case 2: //Стоп вибромотора
							GPIOA->ODR &= ~0b1;
							break;
						case 3: //Старт нагрева воздуха
							GPIOA->ODR |= 0b1<<2;
							isClimatic = 0;
							break;
						case 4: //Стоп нагрева воздуха
							GPIOA->ODR &= ~(0b1<<2);
							isClimatic = 0;
							break;
						case 5: //Старт нагрева крыши
							GPIOC->ODR |= 0b1<<13;
							break; 
						case 6: //Стоп нагрева крыши
							GPIOC->ODR &= ~(0b1<<13);
							break;
						case 7: //Старт светодиодной ленты
							GPIOC->ODR |= 0b1<<4;
							break;
						case 8: //Стоп светодиодной ленты
							GPIOC->ODR &= ~(0b1<<4);
							break;
						case 9: //Открыть вентиляцию
							GPIOA->ODR |= (0b1<<5);
							GPIOA->ODR &= ~(0b1<<11);
							delay(1500);
							GPIOA->ODR &= ~(0b1<<5);
							break;
						case 10: //Закрыть вентиляцию
							GPIOA->ODR |= (0b1<<11);
							GPIOA->ODR &= ~(0b1<<5);
							uint32_t counter = 0;
							while (counter <= AIR_SHUTTERS_CLOSE_TIMEOUT && (GPIOB->IDR & (0b1<<4)) && (GPIOB->IDR & (0b1<<5))) counter++;
							GPIOA->ODR &= ~(0b1<<11);
							break;
						case 11: //Включить проветривание
							GPIOA->ODR |= 0b1<<1;
							break;
						case 12: //Выключить проветривание
							GPIOA->ODR &= ~(0b1<<1);
							break;
						case 13: //Поднять стол
							for (int i = 0; i <= STEP_MOTOR_TABLE_UPPER_TIMEOUT; i++) {
								makeSteps(0b00, 10);
								if (GPIOB->IDR & (0b1<<2)) break;
								if (i == STEP_MOTOR_TABLE_UPPER_TIMEOUT) {
									//Ошибка недоподнятого стола
									msg_tx[0] = 0xFF;
									msg_tx[1] = 0b00001110;
									msg_tx[2] = 1;
									msg_tx[3] = 3;
									msg_tx[5] = 0b10111111;
									for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
									USART1_SendArray(msg_tx, msg_tx[2]+5);
									for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
								}
							}
							break;
						case 14: //Опустить стол
							for (int i = 0; i <= STEP_MOTOR_TABLE_LOWER_TIMEOUT; i++) {
								makeSteps(0b01, 10);
								if (GPIOB->IDR & (0b1<<3)) break;
								if (i == STEP_MOTOR_TABLE_LOWER_TIMEOUT) {
								//Ошибка недоопущенного стола
									msg_tx[0] = 0xFF;
									msg_tx[1] = 0b00001110;
									msg_tx[2] = 1;
									msg_tx[3] = 4;
									msg_tx[5] = 0b10111111;
									for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
									USART1_SendArray(msg_tx, msg_tx[2]+5);
									for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
								} 
							}
							break;
						case 15: //Открыть зарядные лапки дрона
							for (int i = 0; i <= STEP_MOTOR_DRONE_OPEN_TIMEOUT; i++) {
								makeSteps(0b10, 10);
							}
							break;
						case 16: //Закрыть зарядные лапки дрона
							for (int i = 0; i <= STEP_MOTOR_DRONE_HOLD_TIMEOUT; i++) {
								makeSteps(0b11, 10);
								if (GPIOB->IDR & (0b1<<7)) break;
								if (i == STEP_MOTOR_DRONE_HOLD_TIMEOUT) {
									//Ошибка незакрытых лапок
									msg_tx[0] = 0xFF;
									msg_tx[1] = 0b00001110;
									msg_tx[2] = 1;
									msg_tx[3] = 7;
									msg_tx[5] = 0b10111111;
									for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
									USART1_SendArray(msg_tx, msg_tx[2]+5);
									for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
								} 
							}
							break;
						case 17: //Открыть крышу
							PWM_SetPulseWidth(2000);
							for (int i = 0; i <= ROOF_SHUTTERS_OPEN_TIMEOUT; i++) {
								if (i == ROOF_SHUTTERS_OPEN_TIMEOUT && (GPIOB->IDR & 0b1) == 0) {
									//Ошибка недооткрытой крыши
									msg_tx[0] = 0xFF;
									msg_tx[1] = 0b00001110;
									msg_tx[2] = 1;
									msg_tx[3] = 1;
									msg_tx[5] = 0b10111111;
									for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
									USART1_SendArray(msg_tx, msg_tx[2]+5);
									for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
								}
							}
							break;
						case 18: //Закрыть крышу
							PWM_SetPulseWidth(10000);
							for (int i = 0; i <= ROOF_SHUTTERS_CLOSE_TIMEOUT; i++) {
								if (i == ROOF_SHUTTERS_CLOSE_TIMEOUT && (GPIOB->IDR & 0b1<<1) == 0) {
									//Ошибка недозакрытой крыши
									msg_tx[0] = 0xFF;
									msg_tx[1] = 0b00001110;
									msg_tx[2] = 1;
									msg_tx[3] = 2;
									msg_tx[5] = 0b10111111;
									for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
									USART1_SendArray(msg_tx, msg_tx[2]+5);
									for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
								}
							}
							break;
						case 19: //Включить климат контроль
							isClimatic = 1;
							break;
						case 20: //Выключить климат контроль
							isClimatic = 0;
							break;
						default:
							break;
					}
					break;
				default:
					break;
			}
		} 
	} else {
		msg_tx[0] = 0xFF;
		msg_tx[1] = 0b00000110;
		msg_tx[2] = 1;
		msg_tx[3] = 0;
		msg_tx[5] = 0b10111111;
		for (int i = 0; i < msg_tx[2]+5; i++) if (i != (msg_tx[2]+4)-1) msg_tx[(msg_tx[2]+4)-1] += msg_tx[i];
		USART1_SendArray(msg_tx, msg_tx[2]+5);
		for (uint16_t i = 0; i < msg_tx[2]+5; i++) msg_tx[i] = 0b0;
	}
	
	
	for (int i = 0; i < len + 5; i++) msg_rx[start_msg_index][i] = 0;
	start_msg_index++;
	if (start_msg_index == BUFFER_LENGTH) start_msg_index = 0;
}

int main(void) 
{
	//===== Инициализация
	ClockInit();           // Инициализация тактирования микроконтроллера
	GPIO_init();		       // Инициализация выходных/входных портов
	USART1_Init(115200);   // Инициализация USART интерфейса
	PWM_Init();            // Инициализация PWM на PA6
	ADC_Init();            // Инициализация чтения аналогового датчика на PA6 (напряжение акб)
	DHT22_Init();          // Инициализация датчика DHT22
	
	while (true) {
		if (last_msg_index - start_msg_index != 0) read_message();   //Чтение пришедших сообщений
		if (isClimatic) {    // Постоянная проверка температуры в коробке
			uint8_t dht22_data[5] = {0, 0, 0, 0, 0};
			float current_temp = DHT22_GetTemperature(dht22_data);
			float current_humidity = DHT22_GetHumidity(dht22_data);
			if (current_temp <= COOLER_MIN_TEMPERATURE) {
				//Выключение проветривание
				Airing_control(0);
			} else if (current_temp >= COOLER_MAX_TEMPERATURE) { 
				//Включение проветривание
				Airing_control(1);
			}
			if (current_temp <= HEATER_MIN_TEMPERATURE) { 
				//Включение отопления
				GPIOA->ODR |= 0b1<<2;
			} else if (current_temp >= HEATER_MAX_TEMPERATURE) { 
				//Выключение отопления
				GPIOA->ODR &= ~(0b1<<2);
			}
			if (current_humidity > 90.0) {
				//Слишком влажно. Проветрить
				Airing_control(1);
				delay(25000);
				Airing_control(0);
			}
		}
	}
}

void USART1_IRQHandler(void) {
    if (USART1->SR & USART_SR_RXNE) {
			//Приняли сообщение
			uint8_t data = USART1->DR;  // Чтение очищает флаг RXNE
			//Проверили: Первое ли слово
			if (data == 0b10111111) msg_byte_index = 0;
			//Записали в буфер
			msg_rx[last_msg_index][msg_byte_index] = data;
			if (data == 0b11111111) last_msg_index++;
			msg_byte_index++;
			//обновили счётчики
			if (msg_byte_index >= MAX_MESSAGE_LENGTH) msg_byte_index = 0; //Дошли до конца возможной длины сообщения
			if (last_msg_index >= BUFFER_LENGTH) last_msg_index++; //Дошли до конца буфера. Обнуляемся
    }
}
---
[[Droneport_about]]
