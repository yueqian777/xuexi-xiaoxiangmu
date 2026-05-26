package com.intp.study.parking.controller;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.knowledge.dto.KnowledgeCardDto;
import com.intp.study.parking.dto.ConvertParkingLotToBranchQuestionRequest;
import com.intp.study.parking.dto.ConvertParkingLotToKnowledgeRequest;
import com.intp.study.parking.dto.ParkingLotItemDto;
import com.intp.study.parking.dto.SaveParkingLotItemRequest;
import com.intp.study.parking.service.ParkingLotCommandService;
import com.intp.study.parking.service.ParkingLotQueryService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/parking-lot")
public class ParkingLotController {
    private final ParkingLotQueryService parkingLotQueryService;
    private final ParkingLotCommandService parkingLotCommandService;

    public ParkingLotController(
            ParkingLotQueryService parkingLotQueryService,
            ParkingLotCommandService parkingLotCommandService
    ) {
        this.parkingLotQueryService = parkingLotQueryService;
        this.parkingLotCommandService = parkingLotCommandService;
    }

    @GetMapping
    public List<ParkingLotItemDto> list() {
        return parkingLotQueryService.listForCurrentUser();
    }

    @GetMapping("/{id}")
    public ParkingLotItemDto get(@PathVariable long id) {
        return parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ParkingLotItemDto create(@Valid @RequestBody SaveParkingLotItemRequest request) {
        return parkingLotCommandService.create(request);
    }

    @PutMapping("/{id}")
    public ParkingLotItemDto update(@PathVariable long id, @Valid @RequestBody SaveParkingLotItemRequest request) {
        return parkingLotCommandService.update(id, request);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id) {
        parkingLotCommandService.delete(id);
    }

    @PostMapping("/{id}/resolve")
    public ParkingLotItemDto resolve(@PathVariable long id) {
        return parkingLotCommandService.resolve(id);
    }

    @PostMapping("/{id}/convert-to-knowledge-card")
    @ResponseStatus(HttpStatus.CREATED)
    public KnowledgeCardDto convertToKnowledgeCard(
            @PathVariable long id,
            @Valid @RequestBody ConvertParkingLotToKnowledgeRequest request
    ) {
        return parkingLotCommandService.convertToKnowledgeCard(id, request);
    }

    @PostMapping("/{id}/convert-to-branch-question")
    @ResponseStatus(HttpStatus.CREATED)
    public ParkingLotItemDto convertToBranchQuestion(
            @PathVariable long id,
            @RequestBody ConvertParkingLotToBranchQuestionRequest request
    ) {
        return parkingLotCommandService.convertToBranchQuestion(id, request);
    }
}
