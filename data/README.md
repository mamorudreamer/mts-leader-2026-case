# Данные

Исходная выгрузка (`Билетти_база.xlsx`) — учебный материал организаторов центра оценки, поэтому в репозиторий она не входит.

Ожидаемый формат: Excel-файл с листом `feedback_data` и полями
`id, date, source, platform, app_version, user_id, topic, text, rating, sentiment, additional_support_contact, support_reason, region, user_segment`.

Поля `user_name`, `email`, `phone`, если они есть, удаляются при загрузке.
Положите файл как `data/feedback.xlsx` и запустите `python src/run_analysis.py`.
