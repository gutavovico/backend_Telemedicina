"""Codificador QR puro en Python estándar (sin dependencias externas).

Subconjunto necesario para CU16: modo byte, nivel de corrección M,
versiones 1-10 con selección automática de versión y de máscara
mediante penalización (basado en el algoritmo público de Nayuki QR Code
generator, reimplementado para operar sin acceso a PyPI).

El QR embebido en el PDF contiene exclusivamente la URL pública de
validación (diseño decisión 10).
"""

# Versión mínima/máxima soportada
MIN_VERSION = 1
MAX_VERSION = 10

# Nivel de corrección de errores M (permite ~15% de daño)
_ECC_CODEWORDS_PER_BLOCK = {
    1: 10, 2: 16, 3: 26, 4: 18, 5: 24,
    6: 16, 7: 18, 8: 22, 9: 22, 10: 26,
}
_NUM_ERROR_CORRECTION_BLOCKS = {
    1: 1, 2: 1, 3: 1, 4: 2, 5: 2,
    6: 4, 7: 4, 8: 4, 9: 5, 10: 5,
}
_NUM_RAW_DATA_MODULES = {  # codewords totales (datos + ECC)
    1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
    6: 172, 7: 196, 8: 242, 9: 292, 10: 346,
}
_ALIGNMENT_PATTERN_POSITIONS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
    9: [6, 26, 46], 10: [6, 28, 50],
}
_NUM_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}


class QrEncodeError(Exception):
    """El texto no cabe en la versión máxima soportada."""


# --------------------------------------------------------------------------- #
# Reed-Solomon sobre GF(2^8) con polinomio 0x11D
# --------------------------------------------------------------------------- #

def _reed_solomon_compute_divisor(degree: int):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _reed_solomon_multiply(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _reed_solomon_multiply(root, 0x02)
    return result


def _reed_solomon_multiply(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ (0x11D if (z >> 7) != 0 else 0)) & 0xFF
        if ((y >> i) & 1) != 0:
            z ^= x
    return z


def _reed_solomon_compute_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _reed_solomon_multiply(coef, factor)
    return result


# --------------------------------------------------------------------------- #
# Bits de formato y de versión
# --------------------------------------------------------------------------- #

def _get_format_bits(mask: int) -> int:
    # ECL M = 00; 5 bits de datos + 10 BCH, XOR 0x5412
    data = 0x00 << 3 | mask  # 5 bits: formato M + máscara
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ (0x537 if (rem >> 9) != 0 else 0)
    bits = ((data << 10) | rem) ^ 0x5412
    assert bits >> 15 == 0
    return bits


def _get_version_bits(version: int) -> int:
    # Solo versiones >= 7 llevan información de versión (BCH 18,6 con 0x1F25)
    data = version
    rem = data
    for _ in range(12):
        rem = (rem << 1) ^ (0x1F25 if (rem >> 11) != 0 else 0)
    return (data << 12) | rem


# --------------------------------------------------------------------------- #
# Construcción de la matriz
# --------------------------------------------------------------------------- #

class _QrMatrix:
    def __init__(self, version: int):
        if not (MIN_VERSION <= version <= MAX_VERSION):
            raise ValueError("Versión QR fuera de rango")
        self.version = version
        self.size = version * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def _set_function_module(self, x: int, y: int, is_dark: bool):
        self.modules[y][x] = is_dark
        self.is_function[y][x] = True

    def _draw_finder_pattern(self, cx: int, cy: int):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.size and 0 <= y < self.size:
                    dist = max(abs(dx), abs(dy))
                    self._set_function_module(x, y, dist != 2 and dist != 4)

    def _draw_all_function_patterns(self):
        for i in range(self.size):
            self._set_function_module(6, i, i % 2 == 0)  # timing horizontal/vertical
            self._set_function_module(i, 6, i % 2 == 0)
        self._draw_finder_pattern(3, 3)
        self._draw_finder_pattern(self.size - 4, 3)
        self._draw_finder_pattern(3, self.size - 4)
        positions = _ALIGNMENT_PATTERN_POSITIONS[self.version]
        for i, ay in enumerate(positions):
            for j, ax in enumerate(positions):
                if not ((i == 0 and j == 0) or (i == 0 and j == len(positions) - 1)
                        or (i == len(positions) - 1 and j == 0)):
                    self._draw_alignment_pattern(ax, ay)
        # Reserva las áreas de formato y versión como módulos de función
        # (valores dummy que se sobrescriben tras aplicar la máscara elegida).
        # Sin esta reserva, los codewords de datos invadirían esas áreas.
        self._draw_format_bits(0)
        self._draw_version_info()

    def _draw_alignment_pattern(self, cx: int, cy: int):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self._set_function_module(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def _draw_version_info(self):
        if self.version < 7:
            return
        bits = _get_version_bits(self.version)
        for i in range(18):
            bit = ((bits >> i) & 1) != 0
            a = self.size - 11 + (i % 3)
            b = i // 3
            self._set_function_module(a, b, bit)
            self._set_function_module(b, a, bit)

    def _draw_format_bits(self, mask: int):
        bits = _get_format_bits(mask)

        def bit_at(i: int) -> bool:
            return ((bits >> i) & 1) != 0

        # Copia 1 (esquina superior izquierda): 6 + 3 + 6 módulos
        for i in range(6):
            self._set_function_module(8, i, bit_at(i))
        self._set_function_module(8, 7, bit_at(6))
        self._set_function_module(8, 8, bit_at(7))
        self._set_function_module(7, 8, bit_at(8))
        for i in range(9, 15):
            self._set_function_module(14 - i, 8, bit_at(i))
        # Copia 2: 7 módulos verticales (bits 0-6) + 8 horizontales (bits 7-14)
        for i in range(7):
            self._set_function_module(self.size - 1 - i, 8, bit_at(i))
        for i in range(7, 15):
            self._set_function_module(8, self.size - 15 + i, bit_at(i))
        self._set_function_module(self.size - 8, 8, True)  # módulo oscuro fijo

    def _apply_mask(self, mask: int):
        for y in range(self.size):
            for x in range(self.size):
                if self.is_function[y][x]:
                    continue
                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = (x * y) % 2 + (x * y) % 3 == 0
                elif mask == 6:
                    invert = ((x * y) % 2 + (x * y) % 3) % 2 == 0
                else:
                    invert = ((x + y) % 2 + (x * y) % 3) % 2 == 0
                if invert:
                    self.modules[y][x] = not self.modules[y][x]

    def _penalty_score(self) -> int:
        result = 0
        size = self.size
        # N1: secuencias de 5+ del mismo color en filas/columnas
        for y in range(size):
            run_color, run_len = False, 0
            run_history = [0] * 7
            for x in range(size):
                if self.modules[y][x] == run_color:
                    run_len += 1
                    if run_len == 5:
                        result += 3
                    elif run_len > 5:
                        result += 1
                else:
                    run_history = self._finder_penalty_add_history(self.modules[y][x], run_history)
                    if not self.modules[y][x]:
                        result += self._finder_penalty_count_patterns(run_history) * 40
                    run_color = self.modules[y][x]
                    run_len = 1
            result += self._finder_penalty_terminate_and_count(run_color, run_len, run_history) * 40
        for x in range(size):
            run_color, run_len = False, 0
            run_history = [0] * 7
            for y in range(size):
                if self.modules[y][x] == run_color:
                    run_len += 1
                    if run_len == 5:
                        result += 3
                    elif run_len > 5:
                        result += 1
                else:
                    run_history = self._finder_penalty_add_history(self.modules[y][x], run_history)
                    if not self.modules[y][x]:
                        result += self._finder_penalty_count_patterns(run_history) * 40
                    run_color = self.modules[y][x]
                    run_len = 1
            result += self._finder_penalty_terminate_and_count(run_color, run_len, run_history) * 40
        # N2: bloques 2x2 del mismo color
        for y in range(size - 1):
            for x in range(size - 1):
                c = self.modules[y][x]
                if c == self.modules[y][x + 1] == self.modules[y + 1][x] == self.modules[y + 1][x + 1]:
                    result += 3
        # N4: proporción de módulos oscuros
        dark = sum(row.count(True) for row in self.modules)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += k * 10
        return result

    @staticmethod
    def _finder_penalty_add_history(current_run_color: bool, run_history):
        if not current_run_color:
            run_history = run_history[1:] + [0]
        else:
            run_history[-1] += 1
        return run_history

    @staticmethod
    def _finder_penalty_count_patterns(run_history) -> int:
        n = run_history[1]
        core = n > 0 and all(x == n for x in (run_history[2], run_history[3], run_history[4]))
        ending = core and run_history[5] >= 4 * n and run_history[6] >= n
        if core and run_history[0] >= 4 * n and run_history[1] == n:
            return 1
        return 0

    @staticmethod
    def _finder_penalty_terminate_and_count(current_run_color: bool, current_run_length: int, run_history) -> int:
        if current_run_color:
            _QrMatrix._finder_penalty_add_history(current_run_color, run_history)
            current_run_length = 0
        current_run_length += 1
        result = _QrMatrix._finder_penalty_count_patterns(run_history)
        return result

    def _draw_codewords(self, data: bytes):
        assert len(data) * 8 <= len(self.modules) ** 2  # capacidad suficiente
        bit_index = 0

        def get_bit(i: int) -> bool:
            return ((data[i >> 3] >> (7 - (i & 7))) & 1) != 0

        for right in range(self.size - 1, 0, -2):
            if right <= 6:
                right -= 1
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (self.size - 1 - vert) if upward else vert
                    if not self.is_function[y][x] and bit_index < len(data) * 8:
                        self.modules[y][x] = get_bit(bit_index)
                        bit_index += 1


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #

def _num_data_codewords(version: int) -> int:
    return _NUM_RAW_DATA_MODULES[version] - _ECC_CODEWORDS_PER_BLOCK[version] * _NUM_ERROR_CORRECTION_BLOCKS[version]


def _data_capacity_bits(version: int) -> int:
    return _num_data_codewords(version) * 8 - _NUM_REMAINDER_BITS[version]


def _encode_data_codewords(text_bytes: bytes, version: int) -> bytes:
    char_count_bits = 8 if version <= 9 else 16
    capacity = _data_capacity_bits(version)
    bits = []
    # Modo byte: 0100
    bits += [0, 1, 0, 0]
    count = len(text_bytes)
    for i in range(char_count_bits - 1, -1, -1):
        bits.append((count >> i) & 1)
    for byte in text_bytes:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    if len(bits) > capacity:
        raise QrEncodeError("El texto no cabe en la versión QR seleccionada")
    # Terminador (hasta 4 ceros)
    bits += [0] * min(4, capacity - len(bits))
    # Relleno a múltiplo de byte
    bits += [0] * ((8 - len(bits) % 8) % 8)
    # Bytes de relleno alternados 0xEC / 0x11
    data = bytearray()
    for i in range(0, len(bits), 8):
        value = 0
        for b in bits[i:i + 8]:
            value = (value << 1) | b
        data.append(value)
    pad_byte = 0xEC
    while len(data) < _num_data_codewords(version):
        data.append(pad_byte)
        pad_byte = 0x11 if pad_byte == 0xEC else 0xEC
    return bytes(data)


def _add_error_correction(data: bytes, version: int) -> bytes:
    num_blocks = _NUM_ERROR_CORRECTION_BLOCKS[version]
    block_ecc_len = _ECC_CODEWORDS_PER_BLOCK[version]
    raw_count = _num_data_codewords(version)
    assert len(data) == raw_count
    # Los bloques difieren como máximo en 1 byte: los últimos
    # (raw_count % num_blocks) bloques llevan un byte extra.
    num_long_blocks = raw_count % num_blocks
    short_len = raw_count // num_blocks
    blocks = []
    k = 0
    for i in range(num_blocks):
        data_len = short_len + (1 if i >= num_blocks - num_long_blocks else 0)
        dat = data[k:k + data_len]
        k += len(dat)
        ecc = _reed_solomon_compute_remainder(dat, _reed_solomon_compute_divisor(block_ecc_len))
        blocks.append((dat, bytes(ecc)))
    assert k == raw_count
    # Intercalado: primero datos, luego ECC
    result = bytearray()
    max_data = max(len(d) for d, _ in blocks)
    for i in range(max_data):
        for dat, _ in blocks:
            if i < len(dat):
                result.append(dat[i])
    for i in range(block_ecc_len):
        for _, ecc in blocks:
            result.append(ecc[i])
    return bytes(result)


def encode_qr_matrix(text: str):
    """Codifica el texto (UTF-8, modo byte, ECL-M) y devuelve la matriz de módulos.

    Retorna (matriz, version): matriz[y][x] → True si el módulo es oscuro.
    """
    text_bytes = text.encode("utf-8")
    version = None
    for candidate in range(MIN_VERSION, MAX_VERSION + 1):
        char_count_bits = 8 if candidate <= 9 else 16
        needed = 4 + char_count_bits + len(text_bytes) * 8
        if needed <= _data_capacity_bits(candidate):
            version = candidate
            break
    if version is None:
        raise QrEncodeError("El texto supera la capacidad QR máxima soportada (versión 10-M)")
    data_cw = _encode_data_codewords(text_bytes, version)
    all_cw = _add_error_correction(data_cw, version)

    best_matrix = None
    best_penalty = None
    for mask in range(8):
        matrix = _QrMatrix(version)
        matrix._draw_all_function_patterns()
        matrix._draw_codewords(all_cw)
        matrix._apply_mask(mask)
        matrix._draw_format_bits(mask)
        penalty = matrix._penalty_score()
        if best_penalty is None or penalty < best_penalty:
            best_penalty = penalty
            best_matrix = matrix
    return [row[:] for row in best_matrix.modules], version
