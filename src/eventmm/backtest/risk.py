def within_position_limit(
    current_position: int, order_quantity: int, max_position: int
) -> bool:
    return abs(current_position + order_quantity) <= max_position
