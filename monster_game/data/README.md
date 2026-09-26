# Data layout

```
data/
  map/mapN_*.json              # maps + creatures (lore, unique drops, actions, events)
  item/weapon/tier_{A,B,C}.json
  item/equipment/tier_{A,B,C}.json + sets.json
  item/drop/tier_{A,B,C,D}.json
  item/consumable/belt.json
  item/craft/recipes.json
  item/food.json
  item/upgrade.json
```

## Loot
Each monster has unique material + shared commons by tier. Bosses may drop equipment (`kind: equipment` in drop table).

## Craft
`recipes.json`: spend materials (+ optional gold) → equipment. Materials matter.
