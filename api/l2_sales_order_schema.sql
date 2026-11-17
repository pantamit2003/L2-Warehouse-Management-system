-- Additive integration objects for Google Sheets -> L2 Sales Orders.
-- Existing sales_orders / sales_order_items tables and manual UI are not altered.

create table if not exists public.sales_order_api_requests (
    request_key text primary key,
    sales_order_id bigint unique references public.sales_orders(id) on delete cascade,
    order_id text,
    created_at timestamptz not null default now()
);

create or replace function public.create_sales_order_from_sheet(
    p_request_key text,
    p_order jsonb,
    p_items jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_sales_order_id bigint;
    v_order_id text;
    v_item jsonb;
    v_inserted integer;
begin
    if coalesce(trim(p_request_key), '') = '' then
        raise exception 'request_key is required';
    end if;

    if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 then
        raise exception 'At least one item is required';
    end if;

    if upper(coalesce(p_order->>'warehouse', '')) <> 'L2' then
        raise exception 'Only L2 warehouse is accepted';
    end if;

    -- Claim the deterministic request key. A concurrent retry waits on
    -- this unique key and then returns the first request's order.
    insert into public.sales_order_api_requests(request_key)
    values (p_request_key)
    on conflict (request_key) do nothing;

    get diagnostics v_inserted = row_count;

    if v_inserted = 0 then
        select sales_order_id, order_id
          into v_sales_order_id, v_order_id
          from public.sales_order_api_requests
         where request_key = p_request_key;

        if v_order_id is null then
            raise exception 'Existing request key has no completed order mapping';
        end if;

        return jsonb_build_object(
            'status', 'SUCCESS',
            'order_id', v_order_id,
            'duplicate', true
        );
    end if;

    insert into public.sales_orders (
        warehouse, existing_customer, customer_name, email, phone,
        alternate_phone, remark, order_type,
        billing_address_1, billing_address_2, billing_pincode,
        billing_state, billing_city,
        shipping_name, shipping_phone, shipping_address_1,
        shipping_address_2, shipping_pincode, shipping_state,
        shipping_city, same_as_billing, status
    )
    values (
        'L2',
        nullif(p_order->>'existing_customer', ''),
        nullif(p_order->>'customer_name', ''),
        nullif(p_order->>'email', ''),
        nullif(p_order->>'phone', ''),
        nullif(p_order->>'alternate_phone', ''),
        nullif(p_order->>'remark', ''),
        coalesce(nullif(p_order->>'order_type', ''), 'Standard'),
        nullif(p_order->>'billing_address_1', ''),
        nullif(p_order->>'billing_address_2', ''),
        nullif(p_order->>'billing_pincode', ''),
        nullif(p_order->>'billing_state', ''),
        nullif(p_order->>'billing_city', ''),
        nullif(p_order->>'shipping_name', ''),
        nullif(p_order->>'shipping_phone', ''),
        nullif(p_order->>'shipping_address_1', ''),
        nullif(p_order->>'shipping_address_2', ''),
        nullif(p_order->>'shipping_pincode', ''),
        nullif(p_order->>'shipping_state', ''),
        nullif(p_order->>'shipping_city', ''),
        coalesce((p_order->>'same_as_billing')::boolean, false),
        'CREATED'
    )
    returning id, order_id into v_sales_order_id, v_order_id;

    for v_item in select value from jsonb_array_elements(p_items)
    loop
        insert into public.sales_order_items (
            sales_order_id, sku_code, quantity, shelf_life_type,
            mrp, selling_price, discount_amount, is_non_sellable, zone
        )
        values (
            v_sales_order_id,
            nullif(v_item->>'sku_code', ''),
            (v_item->>'quantity')::numeric,
            coalesce(nullif(v_item->>'shelf_life_type', ''), 'None'),
            coalesce(nullif(v_item->>'mrp', '')::numeric, 0),
            coalesce(nullif(v_item->>'selling_price', '')::numeric, 0),
            coalesce(nullif(v_item->>'discount_amount', '')::numeric, 0),
            coalesce(nullif(v_item->>'is_non_sellable', ''), 'No'),
            nullif(v_item->>'zone', '')
        );
    end loop;

    update public.sales_order_api_requests
       set sales_order_id = v_sales_order_id,
           order_id = v_order_id
     where request_key = p_request_key;

    return jsonb_build_object(
        'status', 'SUCCESS',
        'order_id', v_order_id,
        'duplicate', false
    );
end;
$$;

revoke all on function public.create_sales_order_from_sheet(text, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.create_sales_order_from_sheet(text, jsonb, jsonb) to service_role;
