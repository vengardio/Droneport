#include "gpio.h"

int GPIO_init(void) {
	//инициализация GPIO портов
	RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN; //инициализировани GPIOA
	RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN; //инициализировани GPIOB
	RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN; //инициализировани GPIOC
	
	
	
	//Настройка портов GPIOA
	GPIOA->MODER &= 0x3C000000; //Очистка настройки GPIOA MODER регистра
	//General purpose output
	GPIOA->MODER |= (GPIO_MODER_MODER0_0 |   //вибромотор
	                 GPIO_MODER_MODER2_0 |   //нагреватель воздуха
	                 GPIO_MODER_MODER3_0 |   //светодиодная лента
	                 GPIO_MODER_MODER4_0 |   //вентилятор проветривания
	                 GPIO_MODER_MODER5_0 |   //L298N направление 1
	                 GPIO_MODER_MODER11_0);  //L298N направление 2
	GPIOA->OSPEEDR |= (GPIO_OSPEEDER_OSPEEDR0 |
	                    GPIO_OSPEEDER_OSPEEDR2 |
	                    GPIO_OSPEEDER_OSPEEDR3 |
	                    GPIO_OSPEEDER_OSPEEDR4);
	//Alternative function mode
	GPIOA->MODER |= (GPIO_MODER_MODER9_1 |   //USART1_TX
			             GPIO_MODER_MODER10_1);  //USART1_RX
	GPIOA->AFR[1] |= 7<<4;                //AFRH9 TO AF7
	GPIOA->AFR[1] |= 7<<8;                //AFRH10 TO AF7
	//Analog mode
	GPIOA->MODER |= GPIO_MODER_MODER1;       //BAT_VOLTAGE
	//DHT22 mode
	GPIOA->MODER |= (GPIO_MODER_MODER7_0 |
	                 GPIO_MODER_MODER8_0);     //DHT22 general output
	GPIOA->OTYPER |= (GPIO_OTYPER_OT_7 |
	                  GPIO_OTYPER_OT_8);       //DHT22 open drain (we can read IDR
	
	
	//Настройка портов GPIOB
	GPIOB->MODER &= 0x00; //Очистка настройки GPIOB MODER регистра
	//General purpose output
	GPIOB->MODER |= (GPIO_MODER_MODER9_0 |   //TB6600(2, 3) Enable
	                 GPIO_MODER_MODER10_0 |  //TB6600(2, 3) Direction
	                 GPIO_MODER_MODER12_0 |  //TB6600(2, 3) Step
	                 GPIO_MODER_MODER13_0 |  //TB6600(1) Enable
	                 GPIO_MODER_MODER14_0 |  //TB6600(1) Direction
	                 GPIO_MODER_MODER15_0);  //TB6600(1) Step
  //input
	GPIOB->MODER &= ~GPIO_MODER_MODER6;      //PB6 -> Service Key
	GPIOB->MODER &= ~GPIO_MODER_MODER8;      //PB8 -> концевик лапки открыты
										
									 
									 
	//Настройка портов GPIOC
	GPIOC->MODER &= 0x00; //Очистка настройки GPIOB MODER регистра
	//General purpose output
	GPIOC->MODER |= (GPIO_MODER_MODER0_0 |   //LED статус
									 GPIO_MODER_MODER1_0 |
	                 GPIO_MODER_MODER13_0);  //нагрев крыша
	return 1;
}