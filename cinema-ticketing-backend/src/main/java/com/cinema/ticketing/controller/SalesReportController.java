package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.ReportFilter;
import com.cinema.ticketing.dto.ReportViews.*;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.SalesReportService;
import com.cinema.ticketing.service.OccupancyReportService;
import com.cinema.ticketing.service.ReportExportService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.time.LocalDate;

@RestController
@RequestMapping("/api/admin/reports")
public class SalesReportController {
    private final AuthService auth;
    private final SalesReportService sales;
    private final OccupancyReportService occupancy;
    private final ReportExportService exports;
    public SalesReportController(AuthService auth, SalesReportService sales, OccupancyReportService occupancy, ReportExportService exports) {
        this.auth = auth; this.sales = sales; this.occupancy = occupancy; this.exports = exports;
    }

    @ModelAttribute
    void disableCaching(jakarta.servlet.http.HttpServletResponse response) {
        response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
    }

    @GetMapping("/sales")
    public ApiResponse<Sales> sales(@RequestHeader("X-Auth-Token") String token,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(required = false) Long cinemaId, @RequestParam(required = false) Long movieId) {
        auth.requireAdmin(token);
        return ApiResponse.success(sales.sales(new ReportFilter(from, to, cinemaId, movieId)));
    }

    @GetMapping("/occupancy")
    public ApiResponse<Occupancy> occupancy(@RequestHeader("X-Auth-Token") String token,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(required = false) Long cinemaId, @RequestParam(required = false) Long movieId) {
        auth.requireAdmin(token);
        return ApiResponse.success(occupancy.occupancy(new ReportFilter(from, to, cinemaId, movieId)));
    }

    @GetMapping({"/sales/export", "/occupancy/export"})
    public ResponseEntity<byte[]> export(@RequestHeader("X-Auth-Token") String token,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(required = false) Long cinemaId, @RequestParam(required = false) Long movieId,
            jakarta.servlet.http.HttpServletRequest request) {
        auth.requireAdmin(token);
        ReportFilter filter = new ReportFilter(from, to, cinemaId, movieId);
        boolean isSales = request.getRequestURI().endsWith("/sales/export");
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("text/csv;charset=UTF-8"))
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + (isSales ? "sales" : "occupancy") + "-" + from + "-" + to + ".csv\"")
                .body(isSales ? exports.sales(filter) : exports.occupancy(filter));
    }
}
