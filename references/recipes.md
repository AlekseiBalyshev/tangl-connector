# Готовые запросы

Имена категорий и параметров в моделях разные. Перед запросом сверься с
`model_schema` и подставь точные имена.

## Состав модели

```sql
SELECT category, count(*) n, round(sum(total_volume), 2) volume_m3
FROM elements GROUP BY 1 ORDER BY n DESC
```

```sql
SELECT level_name, level_elevation, count(*) n
FROM elements GROUP BY 1, 2 ORDER BY 2
```

## Объёмы

Объём по категориям и этажам:

```sql
SELECT level_name, category, count(*) n, round(sum(total_volume), 2) volume_m3
FROM elements
WHERE category IN ('Стены', 'Перекрытия')
GROUP BY 1, 2 ORDER BY any_value(level_elevation), 2
```

Бетон по этажам и классам (класс – из названия материала):

```sql
SELECT level_name, category, concrete_class, round(sum(volume), 2) volume_m3
FROM materials
WHERE category IN ('Стены', 'Перекрытия') AND concrete_class IS NOT NULL
GROUP BY ALL ORDER BY any_value(level_elevation), category, concrete_class
```

Все материалы с объёмами:

```sql
SELECT material, count(DISTINCT id) elements, round(sum(volume), 2) volume_m3
FROM materials GROUP BY 1 ORDER BY volume_m3 DESC NULLS LAST
```

## Заполнение параметров

Пустой параметр по категориям (служебные элементы исключены):

```sql
SELECT category, type, count(*) n
FROM elements
WHERE NOT service
  AND coalesce(json_extract_string(pars, '$."Код по классификатору"'), '') = ''
GROUP BY 1, 2 ORDER BY n DESC
```

Доля заполнения:

```sql
SELECT count(*) total,
       count(*) FILTER (WHERE coalesce(json_extract_string(pars, '$."Код по классификатору"'), '') = '') empty
FROM elements WHERE NOT service
```

Список элементов для исправления:

```sql
SELECT id, category, type, level_name
FROM elements
WHERE NOT service
  AND coalesce(json_extract_string(pars, '$."Код по классификатору"'), '') = ''
ORDER BY category, type
```

## Несоответствия

Толщина в имени типа не совпадает с параметром:

```sql
SELECT id, type, json_extract_string(pars, '$."Толщина"') thickness
FROM elements
WHERE category = 'Стены'
  AND regexp_extract(type, '(\d+)\s*мм', 1) <> ''
  AND TRY_CAST(json_extract_string(pars, '$."Толщина"') AS DOUBLE)
      <> TRY_CAST(regexp_extract(type, '(\d+)\s*мм', 1) AS DOUBLE)
```

Дубли (одинаковый тип и положение по высоте на одном уровне):

```sql
SELECT type, level_name, bbox_bottom, bbox_top, count(*) n, list(id) ids
FROM elements WHERE NOT service
GROUP BY ALL HAVING count(*) > 1 ORDER BY n DESC
```

## Спецификации

```sql
SELECT type, level_name, count(*) n
FROM elements WHERE category = 'Окна'
GROUP BY 1, 2 ORDER BY 1, 2
```

```sql
SELECT level_name, count(*) n
FROM elements
WHERE category = 'Двери' AND type ILIKE '%EI60%'
GROUP BY 1 ORDER BY any_value(level_elevation)
```

## Сравнение версий (`--compare <старая версия>`)

Надёжно только для моделей из Revit.

Сводка изменений:

```sql
SELECT coalesce(e.category, p.category) category,
       count(*) FILTER (WHERE p.id IS NULL) added,
       count(*) FILTER (WHERE e.id IS NULL) removed,
       count(*) FILTER (WHERE e.id IS NOT NULL AND p.id IS NOT NULL
                        AND (e.type <> p.type OR e.pars::VARCHAR <> p.pars::VARCHAR)) changed
FROM elements e FULL OUTER JOIN prev p ON e.id = p.id
GROUP BY 1 HAVING added + removed + changed > 0 ORDER BY 1
```

Какие параметры изменились у элемента:

```sql
SELECT e.id, k AS parameter,
       json_extract_string(p.pars, '$."' || k || '"') old_value,
       json_extract_string(e.pars, '$."' || k || '"') new_value
FROM elements e JOIN prev p ON e.id = p.id,
     unnest(json_keys(e.pars)) t(k)
WHERE json_extract_string(e.pars, '$."' || k || '"')
      IS DISTINCT FROM json_extract_string(p.pars, '$."' || k || '"')
ORDER BY e.id, k
```

Изменение объёма по категориям:

```sql
SELECT coalesce(e.category, p.category) category,
       round(sum(coalesce(e.total_volume, 0)), 2) new_m3,
       round(sum(coalesce(p.total_volume, 0)), 2) old_m3
FROM elements e FULL OUTER JOIN prev p ON e.id = p.id
GROUP BY 1 HAVING new_m3 <> old_m3 ORDER BY 1
```

Изменение объёма бетона по классам:

```sql
SELECT coalesce(n.concrete_class, o.concrete_class) concrete_class,
       round(coalesce(n.v, 0), 2) new_m3, round(coalesce(o.v, 0), 2) old_m3
FROM (SELECT concrete_class, sum(volume) v FROM materials WHERE concrete_class IS NOT NULL GROUP BY 1) n
FULL OUTER JOIN (SELECT concrete_class, sum(volume) v FROM prev_materials WHERE concrete_class IS NOT NULL GROUP BY 1) o
  USING (concrete_class)
ORDER BY 1
```
