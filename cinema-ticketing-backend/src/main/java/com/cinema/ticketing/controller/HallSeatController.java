package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.HallSeatService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/admin/halls")
public class HallSeatController {
    private final HallSeatService halls;
    private final AuthService auth;
    public HallSeatController(HallSeatService halls,AuthService auth) { this.halls=halls;this.auth=auth; }
    @GetMapping public ApiResponse<List<Map<String,Object>>> list(@RequestHeader("X-Auth-Token") String token,@RequestParam(required=false) Long cinemaId) {
        auth.requireAdmin(token);return ApiResponse.success(halls.halls(cinemaId));
    }
    @PostMapping public ApiResponse<Map<String,Long>> create(@RequestHeader("X-Auth-Token") String token,@Valid @RequestBody HallSeatService.HallInput input) {
        auth.requireAdmin(token);return ApiResponse.success(Map.of("id",halls.create(input)));
    }
    @PutMapping("/{id}") public ApiResponse<Void> update(@RequestHeader("X-Auth-Token") String token,@PathVariable long id,@Valid @RequestBody HallSeatService.HallInput input) {
        auth.requireAdmin(token);halls.update(id,input);return ApiResponse.success(null);
    }
    @DeleteMapping("/{id}") public ApiResponse<Void> delete(@RequestHeader("X-Auth-Token") String token,@PathVariable long id) {
        auth.requireAdmin(token);halls.delete(id);return ApiResponse.success(null);
    }
    @GetMapping("/{id}/seats") public ApiResponse<Map<String,Object>> seats(@RequestHeader("X-Auth-Token") String token,@PathVariable long id) {
        auth.requireAdmin(token);return ApiResponse.success(halls.seats(id));
    }
    @PostMapping("/{id}/seats/fill") public ApiResponse<Map<String,Integer>> fill(@RequestHeader("X-Auth-Token") String token,@PathVariable long id) {
        auth.requireAdmin(token);return ApiResponse.success(Map.of("added",halls.initialize(id)));
    }
    @PostMapping("/{id}/seats") public ApiResponse<Void> createSeat(@RequestHeader("X-Auth-Token") String token,@PathVariable long id,@Valid @RequestBody HallSeatService.SeatInput input) {
        auth.requireAdmin(token);halls.saveSeat(id,null,input);return ApiResponse.success(null);
    }
    @PutMapping("/{id}/seats/{seatId}") public ApiResponse<Void> updateSeat(@RequestHeader("X-Auth-Token") String token,@PathVariable long id,@PathVariable long seatId,@Valid @RequestBody HallSeatService.SeatInput input) {
        auth.requireAdmin(token);halls.saveSeat(id,seatId,input);return ApiResponse.success(null);
    }
    @PutMapping("/{id}/seats/batch") public ApiResponse<Void> batch(@RequestHeader("X-Auth-Token") String token,@PathVariable long id,@Valid @RequestBody HallSeatService.BatchInput input) {
        auth.requireAdmin(token);halls.batch(id,input);return ApiResponse.success(null);
    }
    @DeleteMapping("/{id}/seats/{seatId}") public ApiResponse<Void> deleteSeat(@RequestHeader("X-Auth-Token") String token,@PathVariable long id,@PathVariable long seatId) {
        auth.requireAdmin(token);halls.deleteSeat(id,seatId);return ApiResponse.success(null);
    }
}
