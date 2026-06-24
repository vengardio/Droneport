---
type: software
status: active
---
[[USART Настройка.jpg]]
[[Протокол STM OrangePi.jpg]]

```C
//usart.h
#include "stm32f401xc.h"

#ifndef USART1_H
#define USART1_H

uint32_t usart1div;

void USART1_Init(uint32_t boudrate);
void USART1_SendArray(const uint8_t *data, uint16_t len);
	
#endif
```

```C
//usart.c
#include "usart1.h"

extern uint32_t usart1div;

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
```

```C
//main.c (usart handler)
void USART1_IRQHandler(void) {
    if (USART1->SR & USART_SR_RXNE) {
			//Приняли сообщение
			uint8_t data = USART1->DR;  // Чтение очищает флаг RXNE
			//Проверили: Первое или последнее слово
			if (data == 0b10111111) msg_byte_index = 0;
			if (data == 0b11111111) last_msg_index++;
			//Записали в буфер
			USART1_msg_buffer[last_msg_index][msg_byte_index] = data;
			msg_byte_index++;
			//обновили счётчики
			if (msg_byte_index >= MAX_MESSAGE_LENGTH) msg_byte_index = 0; //Дошли до конца возможной длины сообщения
			if (last_msg_index >= BUFFER_LENGTH) last_msg_index++; //Дошли до конца буфера. Обнуляемся
    }
}
```