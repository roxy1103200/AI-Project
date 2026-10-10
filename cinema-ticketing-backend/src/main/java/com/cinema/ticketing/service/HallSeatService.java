package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import jakarta.validation.constraints.*;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Statement;
import java.time.LocalDateTime;
import java.util.*;

/** All layout writes share hall/seat row locks with ticket creation. */
@Service
@Transactional
@CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, allEntries = true)
public class HallSeatService {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    public HallSeatService(JdbcTemplate jdbc, StringRedisTemplate redis) { this.jdbc = jdbc; this.redis = redis; }

    public record HallInput(@Positive long cinemaId, @NotBlank @Size(max=64) String name,
            @Min(1) @Max(40) int rows, @Min(1) @Max(40) int columns,
            @NotBlank @Pattern(regexp="STANDARD|IMAX|DOLBY") String type,
            @NotBlank @Pattern(regexp="ACTIVE|INACTIVE") String status) {}
    public record SeatInput(@Min(1) @Max(40) int row, @Min(1) @Max(40) int column,
            @NotBlank @Size(max=32) String code, @NotBlank @Pattern(regexp="STANDARD|VIP|COUPLE") String type,
            @NotBlank @Pattern(regexp="AVAILABLE|DISABLED") String status) {}
    public record BatchInput(@NotEmpty @Size(max=1600) List<@Positive Long> ids,
            @NotBlank @Pattern(regexp="AVAILABLE|DISABLED") String status) {}

    @Transactional(readOnly = true)
    @CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, condition = "false")
    public List<Map<String,Object>> halls(Long cinemaId) {
        String sql = "SELECT h.*,c.name cinema_name,(SELECT COUNT(*) FROM seat t WHERE t.hall_id=h.id) seat_count,"
                + "(SELECT COUNT(*) FROM screening s WHERE s.hall_id=h.id) screening_count "
                + "FROM hall h JOIN cinema c ON c.id=h.cinema_id";
        return cinemaId == null ? jdbc.queryForList(sql + " ORDER BY h.cinema_id,h.id")
                : jdbc.queryForList(sql + " WHERE h.cinema_id=? ORDER BY h.id", cinemaId);
    }

    @Transactional(readOnly = true)
    @CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, condition = "false")
    public Map<String,Object> seats(long hallId) {
        var hall = findHall(hallId, false);
        var seats = jdbc.queryForList("SELECT t.*,EXISTS(SELECT 1 FROM order_item oi WHERE oi.seat_id=t.id) has_orders "
                + "FROM seat t WHERE t.hall_id=? ORDER BY t.row_no,t.column_no,t.id", hallId);
        return Map.of("hall", hall, "seats", seats);
    }

    public long create(HallInput input) {
        requireCinema(input.cinemaId(), input.status());
        var key = new GeneratedKeyHolder();
        jdbc.update(connection -> {
            var statement = connection.prepareStatement("INSERT INTO hall(cinema_id,name,row_count,column_count,hall_type,status) VALUES(?,?,?,?,?,?)", Statement.RETURN_GENERATED_KEYS);
            statement.setLong(1,input.cinemaId()); statement.setString(2,input.name().trim());
            statement.setInt(3,input.rows()); statement.setInt(4,input.columns()); statement.setString(5,input.type()); statement.setString(6,input.status());
            return statement;
        }, key);
        if (key.getKey() == null) throw new BusinessException(500,"影厅创建失败");
        long id = key.getKey().longValue();
        initialize(id);
        return id;
    }

    public void update(long id, HallInput input) {
        var hall = findHall(id,true);
        requireCinema(input.cinemaId(),input.status());
        boolean layout = ((Number)hall.get("row_count")).intValue()!=input.rows()
                || ((Number)hall.get("column_count")).intValue()!=input.columns()
                || ((Number)hall.get("cinema_id")).longValue()!=input.cinemaId();
        if (layout && count("SELECT COUNT(*) FROM screening WHERE hall_id=?",id)>0)
            throw new BusinessException(409,"已有排期的影厅不能改变所属影院或布局尺寸，请新建影厅");
        if ("INACTIVE".equals(input.status()) && "ACTIVE".equals(hall.get("status"))) requireNoFutureScreenings(id);
        if (layout) {
            var existing = jdbc.queryForList("SELECT id FROM seat WHERE hall_id=? ORDER BY id FOR UPDATE",Long.class,id);
            requireMutableSeats(id,existing,true);
            jdbc.update("DELETE FROM seat WHERE hall_id=? AND (row_no>? OR column_no>?)",id,input.rows(),input.columns());
        }
        jdbc.update("UPDATE hall SET cinema_id=?,name=?,row_count=?,column_count=?,hall_type=?,status=? WHERE id=?",
                input.cinemaId(),input.name().trim(),input.rows(),input.columns(),input.type(),input.status(),id);
    }

    public void delete(long id) {
        findHall(id,true);
        if(count("SELECT COUNT(*) FROM screening WHERE hall_id=?",id)>0) throw new BusinessException(409,"影厅已关联排期，无法删除");
        var ids=jdbc.queryForList("SELECT id FROM seat WHERE hall_id=? ORDER BY id FOR UPDATE",Long.class,id);
        requireMutableSeats(id,ids,true);
        jdbc.update("DELETE FROM seat WHERE hall_id=?",id);
        jdbc.update("DELETE FROM hall WHERE id=?",id);
    }

    /** Fill missing coordinates only; retain all existing IDs, labels, types and statuses. */
    public int initialize(long id) {
        var hall=findHall(id,true);
        int rows=((Number)hall.get("row_count")).intValue(), columns=((Number)hall.get("column_count")).intValue();
        if(rows<1||rows>40||columns<1||columns>40) throw new BusinessException(409,"现有影厅尺寸超出管理范围，请先调整为 1～40 排/列");
        var occupied=new HashSet<String>();
        var codes=new HashSet<String>();
        for(var seat:jdbc.queryForList("SELECT row_no,column_no,seat_code FROM seat WHERE hall_id=?",id)) {
            if(!occupied.add(seat.get("row_no")+":"+seat.get("column_no"))) throw new BusinessException(409,"影厅存在重复座位位置，请先修正布局");
            codes.add(String.valueOf(seat.get("seat_code")));
        }
        List<Object[]> additions=new ArrayList<>();
        for(int row=1;row<=rows;row++) for(int column=1;column<=columns;column++) {
            if(occupied.contains(row+":"+column)) continue;
            String code="R"+row+"C"+column;
            if(codes.contains(code)) throw new BusinessException(409,"座位编号 "+code+" 已被其他位置使用，请先调整编号");
            additions.add(new Object[]{id,row,column,code});
        }
        if(!additions.isEmpty()) {
            requireCapacityMutable(id);
            jdbc.batchUpdate("INSERT INTO seat(hall_id,row_no,column_no,seat_code,seat_type,status) VALUES(?,?,?,?,'STANDARD','AVAILABLE')",additions);
        }
        return additions.size();
    }

    public void saveSeat(long hallId, Long seatId, SeatInput input) {
        var hall=findHall(hallId,true);
        if(input.row()>((Number)hall.get("row_count")).intValue()||input.column()>((Number)hall.get("column_count")).intValue())
            throw new BusinessException(400,"座位位置超出影厅布局");
        boolean moved=false;
        if(seatId!=null) {
            var own=jdbc.queryForList("SELECT * FROM seat WHERE id=? AND hall_id=? FOR UPDATE",seatId,hallId);
            if(own.isEmpty()) throw new BusinessException(404,"座位不存在或不属于该影厅");
            var seat=own.getFirst();
            moved=((Number)seat.get("row_no")).intValue()!=input.row()||((Number)seat.get("column_no")).intValue()!=input.column()||!seat.get("seat_code").equals(input.code().trim());
            boolean changed=moved||!seat.get("status").equals(input.status())||!seat.get("seat_type").equals(input.type());
            if(changed) requireMutableSeats(hallId,List.of(seatId),moved);
        }
        if(count("SELECT COUNT(*) FROM seat WHERE hall_id=? AND (id<>? OR ? IS NULL) AND ((row_no=? AND column_no=?) OR seat_code=?)",
                hallId,seatId,seatId,input.row(),input.column(),input.code().trim())>0) throw new BusinessException(409,"座位位置或编号已被使用");
        if(seatId==null) requireCapacityMutable(hallId);
        if(seatId==null) jdbc.update("INSERT INTO seat(hall_id,row_no,column_no,seat_code,seat_type,status) VALUES(?,?,?,?,?,?)",
                hallId,input.row(),input.column(),input.code().trim(),input.type(),input.status());
        else jdbc.update("UPDATE seat SET row_no=?,column_no=?,seat_code=?,seat_type=?,status=? WHERE id=?",
                input.row(),input.column(),input.code().trim(),input.type(),input.status(),seatId);
    }

    public void batch(long hallId,BatchInput input) {
        findHall(hallId,true);
        var ids=input.ids().stream().distinct().sorted().toList();
        String placeholders=String.join(",",Collections.nCopies(ids.size(),"?"));
        List<Object> arguments=new ArrayList<>(); arguments.add(hallId); arguments.addAll(ids);
        var existing=jdbc.queryForList("SELECT id FROM seat WHERE hall_id=? AND id IN ("+placeholders+") ORDER BY id FOR UPDATE",Long.class,arguments.toArray());
        if(existing.size()!=ids.size()) throw new BusinessException(404,"部分座位不属于当前影厅");
        requireMutableSeats(hallId,ids,false);
        arguments.clear(); arguments.add(input.status()); arguments.addAll(ids);
        jdbc.update("UPDATE seat SET status=? WHERE id IN ("+placeholders+")",arguments.toArray());
    }

    public void deleteSeat(long hallId,long seatId) {
        findHall(hallId,true);
        if(jdbc.queryForList("SELECT id FROM seat WHERE id=? AND hall_id=? FOR UPDATE",seatId,hallId).isEmpty()) throw new BusinessException(404,"座位不存在");
        requireMutableSeats(hallId,List.of(seatId),true);
        jdbc.update("DELETE FROM seat WHERE id=?",seatId);
    }

    private void requireMutableSeats(long hallId,List<Long> ids,boolean structural) {
        if(ids.isEmpty()) return;
        requireCapacityMutable(hallId);
        String placeholders=String.join(",",Collections.nCopies(ids.size(),"?"));
        List<Object> arguments=new ArrayList<>(ids);
        String sql=structural ? "SELECT COUNT(*) FROM order_item WHERE seat_id IN ("+placeholders+")"
                : "SELECT COUNT(*) FROM order_item oi JOIN ticket_order o ON o.id=oi.order_id JOIN screening s ON s.id=o.screening_id "
                + "WHERE oi.seat_id IN ("+placeholders+") AND o.status IN ('UNPAID','PAID','ISSUED') AND s.end_time>?";
        if(!structural) arguments.add(LocalDateTime.now());
        if(count(sql,arguments.toArray())>0) throw new BusinessException(409,structural?"已有订单记录的座位不能移动、重命名或删除":"部分座位有未结束场次的有效订单，暂不能修改");
        var screenings=jdbc.queryForList("SELECT id FROM screening WHERE hall_id=? AND status='SCHEDULED' AND end_time>? LIMIT 501",Long.class,hallId,LocalDateTime.now());
        if(screenings.size()>500) throw new BusinessException(409,"该影厅活跃排期过多，请先处理排期");
        var keys=new ArrayList<String>(512);
        for(long screening:screenings) for(long id:ids) {
            keys.add("seat:lock:"+screening+":"+id);
            if(keys.size()==512) { requireUnlocked(keys);keys.clear(); }
        }
        requireUnlocked(keys);
    }
    private void requireUnlocked(List<String> keys) {
        if(keys.isEmpty()) return;
        var values=redis.opsForValue().multiGet(keys);
        if(values!=null&&values.stream().anyMatch(Objects::nonNull)) throw new BusinessException(409,"座位正被观众锁定，请稍后再修改");
    }
    private void requireCapacityMutable(long hallId) {
        if (!jdbc.queryForList("SELECT cap.screening_id FROM screening_capacity_snapshot cap JOIN screening s ON s.id=cap.screening_id "
                + "WHERE s.hall_id=? AND s.status='SCHEDULED' AND s.end_time>? LIMIT 1", hallId, LocalDateTime.now()).isEmpty()) {
            throw new BusinessException(409, "影厅存在已锁定可售容量的未结束场次，请在场次结束后调整座位布局");
        }
    }
    private void requireNoFutureScreenings(long hallId) {
        if(count("SELECT COUNT(*) FROM screening WHERE hall_id=? AND status='SCHEDULED' AND end_time>?",hallId,LocalDateTime.now())>0)
            throw new BusinessException(409,"影厅还有未结束排期，需先处理排期再停用");
    }
    private Map<String,Object> findHall(long id,boolean lock) {
        var rows=jdbc.queryForList("SELECT * FROM hall WHERE id=?"+(lock?" FOR UPDATE":""),id);
        if(rows.isEmpty()) throw new BusinessException(404,"影厅不存在");
        return rows.getFirst();
    }
    private void requireCinema(long id,String hallStatus) {
        var rows=jdbc.queryForList("SELECT status FROM cinema WHERE id=? FOR UPDATE",id);
        if(rows.isEmpty()) throw new BusinessException(404,"影院不存在");
        if("ACTIVE".equals(hallStatus)&&!"ACTIVE".equals(rows.getFirst().get("status"))) throw new BusinessException(409,"停用影院下不能启用影厅");
    }
    private long count(String sql,Object... args) { Long value=jdbc.queryForObject(sql,Long.class,args); return value==null?0:value; }
}
