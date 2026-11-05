Never edit generated files by hand. Run the generator instead.
Services should call repositories, e.g. OrderRepository.get_one, and
must not open sessions. You don't need to close them.

- Always use `uv` for commands
- Avoid global state; prefer composables.
  This continues the list item.

```python
# Never do this in a fence.
```

| Rule | Note |
|------|------|
| Do not edit locales | Managed elsewhere |
1. Run the tests! Then commit? Yes.
