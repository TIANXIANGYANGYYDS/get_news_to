from enum import Enum


class NewsSource(str, Enum):
    CLS = "cls"
    JIN10 = "jin10"
    TENJQKA = "tenjqka"
    MORNING_READING = "morning_reading"
    FUPAN_REVIEW = "fupan_review"
    KLINE_SNAPSHOT = "kline_snapshot"
