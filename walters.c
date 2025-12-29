#include <stdint.h>
#include <immintrin.h>

typedef uint8_t uint8x16 __attribute__(( vector_size(sizeof(__m128)) ));

uint8x16 multiplyBy10(uint8x16 a) {
return a * 10;
}

uint8x16 multiplyBy12(uint8x16 a) {
return a * 12;
}

uint8x16 multiplyBy60(uint8x16 a) {
return a * 60;
}

