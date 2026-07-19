# KPI Definitions

All KPI values are calculated from organization-scoped database records.

| KPI | Formula and unit | Missing-data behavior |
|---|---|---|
| Vessel turnaround | Mean `actual_departure - actual_arrival`, hours | 0 when no completed calls |
| Berth utilization | Occupied/active berths divided by berth count, percent | 0 for no berths |
| Vessel waiting | Berth/operation start minus arrival, hours | Excludes calls without both times |
| Moves per hour | Completed vessel moves divided by persisted operation/planned hours | Minimum denominator prevents divide by zero |
| Yard utilization | Occupied physical slots divided by total slots, percent | 0 for no slots |
| Container dwell | Mean current time minus dwell start, days | 0 for empty registry |
| Rehandle risk | Heuristic based on containers above a target and retrieval priority | Labelled operational heuristic |
| Truck turnaround | Exit minus arrival, minutes | Excludes active visits |
| Gate wait | Processing start minus arrival, minutes | Excludes visits not started |
| Gate throughput | Count of completed transactions in filter window | 0 when no visits |
| Equipment availability | Mean persisted availability ratio, percent | 0 when no equipment |
| Reefer compliance | Latest normal readings divided by latest readings, percent | 0 when no readings |
| Appointment compliance | Arrivals within ±15 minutes of appointment, percent | 0 when no visits |
| Incident rate | Active incidents per 1,000 completed moves | Uses minimum move denominator of 1 |

Filters and target comparisons should be applied before aggregation. Forecast-like completion times are labelled estimates and use observed progress divided by elapsed time; they are not certified predictions.
