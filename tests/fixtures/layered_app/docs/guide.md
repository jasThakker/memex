# Developer Guide

## Orders

`OrderService.create` validates input before `OrderRepository.get_one` is called.
See `app.services.order_services.order_service.OrderService` for details.

```python
from app.schema.order import OrderOut
```
