# Корневые сертификаты для доступа к MAX

Платформа MAX использует **сертификаты Минцифры России**. Если контейнеру не
доверяет им, обращения к `platform-api2.max.ru` падают с ошибкой
`CERTIFICATE_VERIFY_FAILED` (это видно в логе backend: `classgo.max`).

## Как починить (любой из способов)

1. **Положите PEM-файл в этот каталог** (он смонтирован в контейнер как `/certs:ro`):

   ```
   certs/russian_trusted_root_ca.pem
   certs/russian_trusted_sub_ca.pem
   ```

   и укажите в `.env`:

   ```
   MAX_CA_BUNDLE=/certs/russian_trusted_root_ca.pem
   ```

2. **Локальная демонстрация без проверки TLS** (только для показа жюри, не для прода):

   ```
   MAX_TLS_INSECURE=1
   ```

## Диагностика

```
python3 scripts/doctor.py
```

Скрипт покажет, валиден ли токен и в чём причина TLS-сбоя.

## Источник сертификатов

Сертификаты Минцифры: `https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt`
и `https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt`
(переименовать в `.pem`; проверить актуальность ссылок перед скачиванием).
